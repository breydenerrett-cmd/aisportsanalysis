"""Tests for src/data/labels.py and its JS twin, web/js/labels.js.

Static, "prove it without running anything" checks in the same spirit as
tests/test_web_structure.py and tests/test_evidence_labels_unified.py:
web/js/labels.js is parsed as text (its TEAM_NAMES/BOOK_LABELS object
literals are written JSON-literal-shaped specifically so this file can
lift them and feed them to json.loads) rather than executed, so these
tests need no JS runtime.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.data import labels

ROOT = Path(__file__).resolve().parent.parent
LABELS_JS = ROOT / "web" / "js" / "labels.js"
TEAMCOLORS_JS = ROOT / "web" / "js" / "teamcolors.js"
ODDS_FILE = ROOT / "data" / "processed" / "odds_multibook.jsonl"


def _extract_js_object(source: str, const_name: str) -> dict:
    """Pull `export const <const_name> = { ... };` out of a JS source
    file and parse it as JSON. labels.js keeps these two object literals
    strictly JSON-shaped (double-quoted keys/values, no trailing comma,
    no comments inside the braces) precisely so this works -- see that
    file's module docstring."""
    match = re.search(
        rf"export const {const_name} = (\{{.*?\}});", source, re.DOTALL
    )
    if not match:
        raise AssertionError(f"could not find `export const {const_name} = {{...}};` in {LABELS_JS}")
    return json.loads(match.group(1))


def _teamcolors_keys(source: str) -> set[str]:
    """Every club abbreviation web/js/teamcolors.js's TEAMS table knows."""
    match = re.search(r"const TEAMS = \{(.*?)\n\};", source, re.DOTALL)
    if not match:
        raise AssertionError(f"could not find `const TEAMS = {{...}};` in {TEAMCOLORS_JS}")
    return set(re.findall(r"^\s*([A-Z]+):\s*\{", match.group(1), re.MULTILINE))


def _observed_book_keys() -> set[str]:
    """Every raw `book` value the odds pipeline has actually emitted."""
    keys: set[str] = set()
    with ODDS_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "book" in row:
                keys.add(row["book"])
    return keys


class TeamNamesCoverageTests(unittest.TestCase):
    def test_thirty_clubs(self):
        self.assertEqual(len(labels.TEAM_NAMES), 30)

    def test_every_teamcolors_key_has_a_name(self):
        teamcolors_keys = _teamcolors_keys(TEAMCOLORS_JS.read_text(encoding="utf-8"))
        self.assertEqual(len(teamcolors_keys), 30, teamcolors_keys)
        for abbr in teamcolors_keys:
            with self.subTest(team=abbr):
                self.assertIn(abbr, labels.TEAM_NAMES)
                entry = labels.TEAM_NAMES[abbr]
                self.assertTrue(entry["name"], f"{abbr} has no name")
                self.assertTrue(entry["full"], f"{abbr} has no full name")

    def test_every_entry_has_city_name_full(self):
        for abbr, entry in labels.TEAM_NAMES.items():
            with self.subTest(team=abbr):
                self.assertEqual(set(entry.keys()), {"city", "name", "full"})

    def test_ath_has_no_city_prefix(self):
        # MLB dropped the Athletics' city prefix; see src/data/parks.py's
        # ALIASES comment. This is the one deliberate empty city.
        self.assertEqual(labels.TEAM_NAMES["ATH"]["city"], "")
        self.assertEqual(labels.TEAM_NAMES["ATH"]["full"], "Athletics")


class BookLabelsCoverageTests(unittest.TestCase):
    def test_every_observed_book_key_has_a_label(self):
        observed = _observed_book_keys()
        self.assertTrue(observed, "no `book` values found in odds_multibook.jsonl")
        for key in observed:
            with self.subTest(book=key):
                self.assertIn(key, labels.BOOK_LABELS)

    def test_labels_are_not_the_raw_provider_key(self):
        # A label that's just the raw key passed through would mean
        # nobody actually filled it in.
        for key, label in labels.BOOK_LABELS.items():
            with self.subTest(book=key):
                self.assertNotEqual(label, key)


class TeamNameHelperTests(unittest.TestCase):
    def test_full_is_default(self):
        self.assertEqual(labels.team_name("SD"), "San Diego Padres")

    def test_city_and_name_forms(self):
        self.assertEqual(labels.team_name("SD", "city"), "San Diego")
        self.assertEqual(labels.team_name("SD", "name"), "Padres")

    def test_case_insensitive(self):
        self.assertEqual(labels.team_name("sd"), "San Diego Padres")

    def test_unknown_abbreviation_passes_through_unchanged(self):
        self.assertEqual(labels.team_name("XYZ"), "XYZ")
        self.assertEqual(labels.team_name("xyz", "city"), "xyz")

    def test_falsy_input_passes_through_unchanged(self):
        self.assertIsNone(labels.team_name(None))
        self.assertEqual(labels.team_name(""), "")


class BookLabelHelperTests(unittest.TestCase):
    def test_known_key(self):
        self.assertEqual(labels.book_label("williamhill_us"), "Caesars")
        self.assertEqual(labels.book_label("fanduel"), "FanDuel")

    def test_case_insensitive(self):
        self.assertEqual(labels.book_label("FanDuel".lower()), "FanDuel")
        self.assertEqual(labels.book_label("BETMGM"), "BetMGM")

    def test_unknown_key_passes_through_unchanged(self):
        self.assertEqual(labels.book_label("some_new_book"), "some_new_book")

    def test_falsy_input_passes_through_unchanged(self):
        self.assertIsNone(labels.book_label(None))
        self.assertEqual(labels.book_label(""), "")


class JsPythonParityTests(unittest.TestCase):
    """The drift guard: web/js/labels.js and src/data/labels.py must
    carry byte-for-byte the same data. There is no shared object across
    the language boundary (the way
    tests/test_evidence_labels_unified.py pins one within Python), so
    this parses the JS source and compares parsed data instead."""

    @classmethod
    def setUpClass(cls):
        cls.js_source = LABELS_JS.read_text(encoding="utf-8")

    def test_team_names_match(self):
        js_team_names = _extract_js_object(self.js_source, "TEAM_NAMES")
        self.assertEqual(js_team_names, labels.TEAM_NAMES)

    def test_book_labels_match(self):
        js_book_labels = _extract_js_object(self.js_source, "BOOK_LABELS")
        self.assertEqual(js_book_labels, labels.BOOK_LABELS)


if __name__ == "__main__":
    unittest.main()
