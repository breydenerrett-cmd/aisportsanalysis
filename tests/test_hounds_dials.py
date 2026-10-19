"""The rulebook's dials (src/hounds/dials.py): plain words for every knob, a trigger for every dog, the
current values and "last changed" from the learning ledger, and the same wording in Python and in the page.

No FastAPI, no network. The page half (``dialText`` in web/js/hounds-rulebook.js) runs under node and is
skipped without it.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from src.hounds import dials
from src.hounds.learning import ledger as L
from src.hounds.learning import tunables
from tests.hounds_web_runner import HAS_NODE, run_js

CFG = tunables.load()
PACK = json.loads((Path(__file__).resolve().parent.parent / "config" / "house_pack.json").read_text(encoding="utf-8"))
BANNED = re.compile(r"\bedge\b|\block\b|\bprofit|guarantee|can'?t lose|sure thing|free money", re.IGNORECASE)


def grid(knob):
    n = int(round((knob.hi - knob.lo) / knob.step))
    return [round(knob.lo + i * knob.step, 6) for i in range(n + 1)]


class EveryKnobHasPlainWords(unittest.TestCase):
    def test_every_declared_knob_has_an_entry_and_every_entry_has_a_knob(self):
        declared = {(hid, name) for hid, tun in CFG.items() for name in tun.knobs}
        self.assertEqual(declared, set(dials.DIAL_WORDS),
                         "a knob without plain words (or words for a knob that is gone)")

    def test_the_words_do_not_use_the_pages_banned_vocabulary(self):
        for key, (label, scale, unit) in dials.DIAL_WORDS.items():
            self.assertIsNone(BANNED.search(label), (key, label))
            for knob in CFG[key[0]].knobs.values():
                if knob.name == key[1]:
                    for v in grid(knob):
                        self.assertIsNone(BANNED.search(dials.dial_text(scale, unit, v)))

    def test_every_house_dog_has_a_plain_trigger(self):
        ids = {h["id"] for h in PACK["hounds"]}
        self.assertEqual(ids - set(dials.TRIGGERS), set(), "a house dog with no 'this dog bets when ...' line")
        for hid, text in dials.TRIGGERS.items():
            self.assertTrue(text and not text.endswith("."), hid)
            self.assertIsNone(BANNED.search(text), (hid, text))

    def test_the_steam_example_reads_the_way_the_owner_asked(self):
        label, scale, unit = dials.DIAL_WORDS[("steamy_setter", "MOVE")]
        self.assertEqual(f"{label}: {dials.dial_text(scale, unit, 0.03)}", "Steam needed: 3 points")

    def test_number_and_unit_wording(self):
        self.assertEqual(dials.dial_text(100, "points", 0.035), "3.5 points")
        self.assertEqual(dials.dial_text(1, "days", 1), "1 day")
        self.assertEqual(dials.dial_text(1, "votes", 2), "2 votes")
        self.assertEqual(dials.dial_text(100, "%", 0.5), "50%")
        self.assertEqual(dials.dial_text(1, "pitches", 120), "120 pitches")


class TheRulebookPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scopes = {"house": L.Scope.house(Path(self.tmp.name) / "h"), "user": L.Scope.user(Path(self.tmp.name) / "u")}

    def test_a_dog_never_changed_says_so_and_shows_the_declared_values(self):
        rb = dials.rulebook("steamy_setter", scope_map=self.scopes)
        self.assertTrue(rb["tunable"])
        self.assertIsNone(rb["last_changed"])
        self.assertEqual(rb["champion_version"], 1)
        (d,) = rb["dials"]
        self.assertEqual((d["name"], d["current"], d["text"], d["label"]), ("MOVE", 0.03, "3 points", "Steam needed"))
        self.assertEqual((d["min"], d["max"], d["step"]), (0.02, 0.05, 0.005))
        self.assertEqual(rb["trigger"], dials.TRIGGERS["steamy_setter"])
        self.assertIn("moved toward", rb["rule_text"])
        self.assertIn("Only the referee", rb["only_the_referee"])

    def test_a_promotion_moves_the_current_value_and_names_the_version_and_the_referee(self):
        log = L.log_for(self.scopes["house"])
        from datetime import datetime, timezone
        when = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
        log.append(L.K_PROMOTION, now=when, hound_id="steamy_setter", lineage_key="steamy_setter", from_version=1,
                   to_version=2, params={"MOVE": 0.04}, applied=True, effective_utc="2026-10-12T15:00:00Z",
                   challenger_id="c1", kind_of="pack", scope="house")
        rb = dials.rulebook("steamy_setter", scope_map=self.scopes)
        self.assertEqual(rb["champion_version"], 2)
        self.assertEqual(rb["dials"][0]["current"], 0.04)
        self.assertEqual(rb["dials"][0]["text"], "4 points")
        self.assertEqual(rb["last_changed"], {"version": 2, "utc": "2026-10-12T15:00:00Z", "by": "the referee"})

    def test_an_unreadable_ledger_reads_as_never_changed_not_as_an_error(self):
        path = self.scopes["house"].events
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json\n", encoding="utf-8")
        rb = dials.rulebook("steamy_setter", scope_map=self.scopes)
        self.assertIsNone(rb["last_changed"])
        self.assertEqual(rb["dials"][0]["current"], 0.03)

    def test_a_dog_with_no_dials_has_a_rule_a_trigger_and_no_dials(self):
        rb = dials.rulebook("coin_flip_collie", scope_map=self.scopes)
        self.assertFalse(rb["tunable"])
        self.assertEqual(rb["dials"], [])
        self.assertEqual(rb["trigger"], dials.TRIGGERS["coin_flip_collie"])

    def test_an_unknown_or_builders_dog_gets_the_generic_trigger(self):
        rb = dials.rulebook("u-abc123", rule_text="Bet the home dog.", scope_map=self.scopes)
        self.assertEqual((rb["tunable"], rb["rule_text"], rb["trigger"]), (False, "Bet the home dog.", dials.GENERIC_TRIGGER))


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePageWordsEveryDialTheSameWay(unittest.TestCase):
    def test_python_and_javascript_agree_on_every_grid_point_of_every_dial(self):
        cases = []
        for (hid, name), (label, scale, unit) in dials.DIAL_WORDS.items():
            knob = CFG[hid].knobs[name]
            for v in grid(knob):
                cases.append({"scale": scale, "unit": unit, "value": v, "py": dials.dial_text(scale, unit, v)})
        out = run_js("import { dialText } from './hounds-rulebook.js';\n"
                     f"const cases = {json.dumps(cases)};\n"
                     "console.log(JSON.stringify(cases.map((c) => dialText({scale: c.scale, unit: c.unit}, c.value))));\n")
        self.assertEqual(out, [c["py"] for c in cases])
        self.assertGreater(len(cases), 60)


if __name__ == "__main__":
    unittest.main()
