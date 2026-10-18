"""The per-game "where they disagree" table (src/hounds/desk/disagree.py): pure, no files."""

from __future__ import annotations

import unittest

from src.hounds.desk import disagree, roles

PACKET = {"slots": [{"slot_id": "moneyline", "market": "moneyline", "label": "A at B moneyline"},
                    {"slot_id": "total", "market": "total", "label": "A at B total"}]}


def take(slot, selection, price=-110, probability=0.55):
    return {"slot_id": slot, "selection": selection, "price": price, "book": "alpha", "probability": probability}


def view(**overrides):
    base = {h["id"]: {"takes": [], "struck": []} for h in roles.HOUNDS}
    base.update(overrides)
    return base


class SlotStatus(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(disagree.slot_status([]), "none")
        self.assertEqual(disagree.slot_status([{"hound_id": "a", "selection": "X"}]), "lone")
        self.assertEqual(disagree.slot_status([{"hound_id": "a", "selection": "X"},
                                               {"hound_id": "b", "selection": "X"}]), "agree")
        self.assertEqual(disagree.slot_status([{"hound_id": "a", "selection": "X"},
                                               {"hound_id": "b", "selection": "Y"}]), "split")


class TheTable(unittest.TestCase):
    def test_a_split_is_named_with_each_hounds_side(self):
        table = disagree.build(PACKET, view(
            desk_fader={"takes": [take("moneyline", "A")], "struck": []},
            desk_square={"takes": [take("moneyline", "B")], "struck": []}))
        ml = table["slots"][0]
        self.assertEqual(ml["status"], "split")
        self.assertEqual(ml["takers"], 2)
        self.assertEqual(ml["hounds"]["desk_fader"]["selection"], "A")
        self.assertEqual(ml["hounds"]["desk_square"]["selection"], "B")
        self.assertEqual(ml["hounds"]["desk_ai"], {"decision": "PASS"})
        self.assertEqual(table["slots"][1]["status"], "none")
        self.assertEqual(table["counts"], {"split": 1, "agree": 0, "lone": 0, "none": 1})

    def test_every_hound_is_in_every_row_and_in_roster_order(self):
        table = disagree.build(PACKET, view())
        for row in table["slots"]:
            self.assertEqual(list(row["hounds"]), [h["id"] for h in roles.HOUNDS])

    def test_an_unanswered_hound_is_unanswered_not_a_pass_and_is_not_a_taker(self):
        table = disagree.build(PACKET, view(desk_sharp=None, desk_fader={"takes": [take("total", "Over")],
                                                                          "struck": []}))
        total = table["slots"][1]
        self.assertEqual(total["hounds"]["desk_sharp"], {"decision": "unanswered"})
        self.assertEqual(total["status"], "lone")

    def test_a_code_strike_is_shown_beside_the_pass(self):
        table = disagree.build(PACKET, view(desk_ai={"takes": [], "struck": [
            {"slot_id": "moneyline", "selection": "A", "rule": "R2", "reason": "too short"}]}))
        cell = table["slots"][0]["hounds"]["desk_ai"]
        self.assertEqual(cell["decision"], "PASS")
        self.assertEqual(cell["struck"][0]["rule"], "R2")

    def test_the_note_says_agreement_is_not_confirmation(self):
        self.assertIn("not confirmation", disagree.build(PACKET, view())["note"])


if __name__ == "__main__":
    unittest.main()
