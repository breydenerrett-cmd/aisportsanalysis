"""The registered ten-entry ceiling, applied at admission.

Kept in its own file, against its own module, deliberately: this is a
DIFFERENT defect from the candidate-enumeration one
(`tests/test_card_v2_candidate_enumeration.py`), and neither one's evidence
should be readable as the other's.
"""

from __future__ import annotations

import unittest

from src.analysis import best_bets_card
from src.appstate import ceiling_admission


def _entry(key, *, cls="pick", score=1.0, locked=False):
    return {"player_id": key, "game_id": None, "bet": f"bet {key}",
            "entry_class": cls, "score": score, "locked": locked}


class Admit(unittest.TestCase):

    def test_a_carried_entry_keeps_its_slot(self):
        carried = [_entry("a", locked=True)]
        admitted, refused = ceiling_admission.admit(
            carried, [_entry("b")], ceiling=10)
        self.assertEqual(["a", "b"], [e["player_id"] for e in admitted])
        self.assertEqual([], refused)

    def test_the_eleventh_entry_is_refused_a_slot_not_a_published_one(self):
        """The owner's own words, 2026-09-16 about 00:45Z: 'an eleventh
        entry that passed every gate is refused a slot rather than a
        published fill being withdrawn'."""
        carried = [_entry(str(i), locked=True) for i in range(10)]
        admitted, refused = ceiling_admission.admit(
            carried, [_entry("new")], ceiling=10)
        self.assertEqual(10, len(admitted))
        self.assertEqual(1, len(refused))
        self.assertEqual("new", refused[0]["player_id"])
        self.assertEqual(ceiling_admission.CEILING_FULL,
                         refused[0]["admission_refused_reason"])
        # Nothing already published was removed.
        self.assertEqual([str(i) for i in range(10)],
                         [e["player_id"] for e in admitted])

    def test_fresh_entries_fill_the_room_in_rank_order(self):
        carried = [_entry("held", locked=True)]
        fresh = [_entry("low", score=0.01), _entry("fill", cls="fill",
                                                   score=9.0),
                 _entry("high", score=5.0)]
        admitted, refused = ceiling_admission.admit(carried, fresh, ceiling=3)
        self.assertEqual(["held", "high", "low"],
                         [e["player_id"] for e in admitted])
        self.assertEqual(["fill"], [e["player_id"] for e in refused])

    def test_a_repeated_key_is_one_bet_not_two(self):
        carried = [_entry("a", locked=True)]
        admitted, refused = ceiling_admission.admit(
            carried, [_entry("a"), _entry("b")], ceiling=10)
        self.assertEqual(["a", "b"], [e["player_id"] for e in admitted])
        self.assertEqual([], refused)

    def test_nothing_is_mutated_in_place(self):
        carried = [_entry("a", locked=True)]
        fresh = [_entry("b")]
        before = (dict(carried[0]), dict(fresh[0]))
        ceiling_admission.admit(carried, fresh, ceiling=10)
        self.assertEqual(before[0], carried[0])
        self.assertEqual(before[1], fresh[0])


class Walk(unittest.TestCase):

    def test_the_ceiling_holds_across_a_day_of_publishes(self):
        """The 2026-09-22 shape, reduced: entries accumulate and lock run
        after run. The live ledger let the card reach 14; admission holds
        it at 10 and records what it refused."""
        snapshots = []
        for n in (3, 5, 6, 12, 13, 14):
            snapshots.append({
                "published_utc": f"2026-09-22T{n:02d}:00:00+00:00",
                "entries": [_entry(str(i), locked=True) for i in range(n)],
            })
        walked = ceiling_admission.walk(snapshots, ceiling=10)
        self.assertEqual([3, 5, 6, 12, 13, 14],
                         [r["listed_actual"] for r in walked])
        self.assertEqual([3, 5, 6, 10, 10, 10],
                         [r["listed_under_admission"] for r in walked])
        self.assertEqual([0, 0, 0, 2, 3, 4],
                         [r["over_ceiling_actual"] for r in walked])
        for row in walked:
            self.assertEqual(0, row["over_ceiling_under_admission"])

    def test_the_registered_ceiling_is_ten(self):
        self.assertEqual(10, best_bets_card.V2.ceiling)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
