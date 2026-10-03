"""src/situation/record.py: the one shape every sport's situation is written in."""

from __future__ import annotations

import unittest

from src.situation import record as rec


def make(**kw):
    base = dict(family="form", name="streak", value=3, unit="games", sample={"games": 9},
                as_of="2025-09-27", source="results store: 3 games", sentence="NYY has won 3 straight.",
                side="away")
    base.update(kw)
    return rec.factor(**base)


def build(factors=(), missing=(), display=None, as_of="2025-09-28"):
    return rec.build(sport="mlb", subject={"game_pk": 1}, as_of=as_of, as_of_basis="test",
                     families=("rest_and_rhythm", "form", "stakes"), sides=("away", "home"),
                     factors=factors, missing=missing, display=display)


class TheFactorShape(unittest.TestCase):
    def test_a_factor_carries_every_field_the_plan_names(self):
        f = make(detail={"type": "win"})
        for key in ("family", "name", "side", "value", "unit", "sample", "as_of", "source", "sentence", "detail"):
            self.assertIn(key, f)

    def test_a_value_is_one_scalar(self):
        for bad in (None, [1, 2], {"a": 1}, (1, 2)):
            with self.assertRaises(rec.RecordError, msg=repr(bad)):
                make(value=bad)
        self.assertEqual(make(value=True)["value"], True)
        self.assertEqual(make(value="bye")["value"], "bye")
        self.assertEqual(make(value=0)["value"], 0)       # zero is a value, not a gap

    def test_a_float_is_rounded_and_never_nan(self):
        self.assertEqual(make(value=1 / 3)["value"], 0.3333)
        with self.assertRaises(rec.RecordError):
            make(value=float("nan"))
        with self.assertRaises(rec.RecordError):
            make(value=float("inf"))

    def test_names_must_be_path_safe_words(self):
        for kw in ({"family": "Form"}, {"name": "last 10"}, {"side": "Away"}, {"name": ""}):
            with self.assertRaises(rec.RecordError, msg=str(kw)):
                make(**kw)

    def test_a_factor_needs_a_sentence_and_a_source(self):
        with self.assertRaises(rec.RecordError):
            make(sentence="  ")
        with self.assertRaises(rec.RecordError):
            make(source="")

    def test_a_gap_needs_a_reason(self):
        self.assertEqual(rec.gap("form", "streak", "no games", side="home")["reason"], "no games")
        with self.assertRaises(rec.RecordError):
            rec.gap("form", "streak", " ")


class TheCutOff(unittest.TestCase):
    def test_a_factor_stamped_on_the_cutoff_is_not_published_and_is_listed_as_missing(self):
        leak = make(name="leak", as_of="2025-09-28")           # the game's own date
        later = make(name="later", as_of="2025-09-29")
        sound = make(name="sound", as_of="2025-09-27")
        r = build([leak, later, sound])
        self.assertEqual([f["name"] for f in r["factors"]], ["sound"])
        self.assertEqual({m["name"] for m in r["missing"]}, {"leak", "later"})
        self.assertTrue(all("not before the record's cut-off" in m["reason"] for m in r["missing"]))

    def test_a_clean_record_has_no_problems(self):
        self.assertEqual(rec.problems(build([make()])), [])

    def test_problems_names_a_tampered_stamp(self):
        r = build([make()])
        r["factors"][0]["as_of"] = "2025-10-01"
        self.assertTrue(any("cut-off" in p for p in rec.problems(r)))

    def test_instants_compare_as_instants(self):
        ok = make(as_of="2026-10-10T22:59:59Z")
        r = rec.build(sport="ufc", subject={}, as_of="2026-10-10T23:00:00Z", as_of_basis="t",
                      families=("form",), sides=("a", "b"), factors=[ok], missing=[])
        self.assertEqual(len(r["factors"]), 1)
        at = make(name="at", as_of="2026-10-10T23:00:00Z")      # at the instant: not before it
        r = rec.build(sport="ufc", subject={}, as_of="2026-10-10T23:00:00Z", as_of_basis="t",
                      families=("form",), sides=("a", "b"), factors=[at], missing=[])
        self.assertEqual(r["factors"], [])


class TheRecord(unittest.TestCase):
    def test_factors_are_ordered_by_family_then_name_then_side_regardless_of_input_order(self):
        a = make(family="stakes", name="series_state", side="game")
        b = make(family="rest_and_rhythm", name="days_since_last_game", side="home")
        c = make(family="rest_and_rhythm", name="days_since_last_game", side="away")
        d = make(family="form", name="last_10", side="away")
        one = build([a, b, c, d])
        two = build([d, c, b, a])
        self.assertEqual(one, two)
        self.assertEqual([(f["family"], f["name"], f["side"]) for f in one["factors"]],
                         [("rest_and_rhythm", "days_since_last_game", "away"),
                          ("rest_and_rhythm", "days_since_last_game", "home"),
                          ("form", "last_10", "away"), ("stakes", "series_state", "game")])

    def test_a_factor_in_an_unknown_family_is_moved_to_missing(self):
        r = build([make(family="weather")])
        self.assertEqual(r["factors"], [])
        self.assertEqual(len(r["missing"]), 1)

    def test_duplicate_gaps_are_written_once(self):
        g = rec.gap("form", "streak", "no games")
        self.assertEqual(len(build(missing=[g, dict(g)])["missing"]), 1)

    def test_display_is_stored_as_indexes_into_factors(self):
        a, b = make(name="a_fact"), make(name="b_fact", side="home")
        r = build([a, b], display=[("form", "b_fact", "home"), ("form", "a_fact", "away"),
                                   ("form", "not_there", "away")])
        names = [r["factors"][i]["name"] for i in r["display"]]
        self.assertEqual(names, ["b_fact", "a_fact"])

    def test_display_lines_give_each_sentence_an_evidence_path_that_resolves(self):
        r = build([make(sentence="NYY has won 3 straight.")], display=[("form", "streak", "away")])
        lines = rec.display_lines(r)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["sentence"], "NYY has won 3 straight.")
        path = lines[0]["evidence"]["path"]
        self.assertEqual(path, "situation.factors.0.value")
        self.assertEqual(r["factors"][0]["value"], lines[0]["evidence"]["value"])

    def test_display_lines_tolerate_nothing(self):
        self.assertEqual(rec.display_lines(None), [])
        self.assertEqual(rec.display_lines({}), [])
        self.assertEqual(rec.display_lines({"factors": [], "display": [3]}), [])

    def test_display_lines_respect_the_limit(self):
        fs = [make(name=f"f{i}") for i in range(8)]
        r = build(fs, display=[("form", f"f{i}", "away") for i in range(8)])
        self.assertEqual(len(rec.display_lines(r, limit=6)), 6)


class ThePacketSection(unittest.TestCase):
    def setUp(self):
        self.r = build([make(detail={"type": "win"}),
                        make(family="stakes", name="series_state", side="game", value=2, unit="game number",
                             sentence="Game 2 of the Division Series (best of 5).", sample={}),
                        make(name="streak", side="home", value=1, sentence="BOS lost its last game.")],
                       missing=[rec.gap("stakes", "playoff_race", "not in the data")])
        self.section = rec.packet_section(self.r)

    def test_it_has_the_sections_shape(self):
        self.assertEqual(set(self.section), {"as_of", "as_of_basis", "values"})
        self.assertEqual(self.section["as_of"], "2025-09-28")

    def test_factors_nest_family_name_side_so_a_path_reads_like_a_sentence(self):
        factors = self.section["values"]["factors"]
        self.assertEqual(factors["form"]["streak"]["away"]["value"], 3)
        self.assertEqual(factors["form"]["streak"]["home"]["value"], 1)
        self.assertEqual(factors["stakes"]["series_state"]["game"]["value"], 2)

    def test_a_leaf_drops_what_the_path_already_says(self):
        leaf = self.section["values"]["factors"]["form"]["streak"]["away"]
        self.assertEqual(set(leaf), {"value", "unit", "sample", "as_of", "source", "sentence", "detail"})
        self.assertNotIn("family", leaf)
        self.assertNotIn("side", leaf)

    def test_missing_and_how_to_read_ride_along(self):
        values = self.section["values"]
        self.assertEqual(values["missing"][0]["name"], "playoff_race")
        self.assertEqual(len(values["how_to_read"]), 4)
        self.assertIn("away, home, game", values["how_to_read"][1])

    def test_the_section_is_json_clean_and_deterministic(self):
        import json
        self.assertEqual(json.dumps(self.section, sort_keys=True), json.dumps(rec.packet_section(self.r), sort_keys=True))


class TheSentenceNumberRule(unittest.TestCase):
    def test_a_number_the_factor_holds_is_supported(self):
        f = make(value=3, sample={"games": 9}, sentence="NYY has won 3 straight in 9 games.")
        self.assertEqual(rec.unsupported_sentence_numbers(f), [])

    def test_a_number_the_factor_does_not_hold_is_found(self):
        f = make(value=3, sentence="NYY has won 3 straight, 7 of the last 10.")
        self.assertEqual(rec.unsupported_sentence_numbers(f), ["7", "10"])

    def test_dates_and_clock_times_are_not_numbers(self):
        f = make(value=3, sentence="3 days since 2025-09-25 at 7:05.")
        self.assertEqual(rec.unsupported_sentence_numbers(f), [])

    def test_a_percentage_matches_a_fraction_at_the_precision_written(self):
        f = make(value=0.6667, unit="rate", sentence="A 67% win rate.")
        self.assertEqual(rec.unsupported_sentence_numbers(f), [])
        self.assertEqual(rec.unsupported_sentence_numbers(make(value=0.6667, sentence="A 70% win rate.")), ["70%"])

    def test_a_negative_margin_is_found_as_its_size(self):
        f = make(value=2, detail={"run_margin": -4}, sentence="Outscored by 4 runs.")
        self.assertEqual(rec.unsupported_sentence_numbers(f), [])

    def test_numbers_inside_detail_lists_count(self):
        f = make(value=1, detail={"meetings": [{"away_score": 4, "home_score": 0}]},
                 sentence="BOS won 4-0.")
        self.assertEqual(rec.unsupported_sentence_numbers(f), [])


if __name__ == "__main__":
    unittest.main()
