"""The lead/lag response table, pinned on synthetic measured events."""

import unittest

from src.research import leadlag


def _event(first=("book_a",), moves=None, stale=None, ladder=None,
           books=None):
    moves = moves or {}
    return {
        "excluded": None,
        "first_movers": list(first),
        "moves": moves,
        "stale_books": stale or {},
        "books": sorted(books if books is not None
                        else set(moves) | set(first)),
        "ladder_minutes": ladder or {"25%": 5.0, "50%": 10.0,
                                     "75%": None, "100%": None},
    }


def _fleet(n, fast="book_a", slow="book_b"):
    """n events where `fast` moves at 5 minutes and `slow` at 45."""
    return [_event(first=(fast,),
                   moves={fast: {"minutes": 5.0, "magnitude": 0.02},
                          slow: {"minutes": 45.0, "magnitude": 0.02}})
            for _ in range(n)]


class FloorTests(unittest.TestCase):
    def test_below_the_event_floor_there_is_no_table(self):
        result = leadlag.response_table(_fleet(29))
        self.assertIn("skipped", result)
        self.assertIn("29", result["skipped"])

    def test_excluded_events_do_not_count_toward_the_floor(self):
        events = _fleet(29) + [{"excluded": "too few books"}]
        self.assertIn("skipped", leadlag.response_table(events))

    def test_a_rarely_seen_book_gets_no_median(self):
        events = _fleet(29)
        events.append(_event(
            first=("book_a",),
            moves={"book_a": {"minutes": 5.0, "magnitude": 0.02},
                   "book_b": {"minutes": 45.0, "magnitude": 0.02},
                   "book_rare": {"minutes": 1.0, "magnitude": 0.02}}))
        table = leadlag.response_table(events)
        self.assertIn("note", table["books"]["book_rare"])
        self.assertNotIn("median_minutes", table["books"]["book_rare"])


class TableTests(unittest.TestCase):
    def test_medians_and_first_mover_counts_read_off_the_fixture(self):
        table = leadlag.response_table(_fleet(30))
        self.assertEqual(table["events"], 30)
        self.assertEqual(table["first_mover_counts"], {"book_a": 30})
        self.assertEqual(table["books"]["book_a"]["median_minutes"], 5.0)
        self.assertEqual(table["books"]["book_b"]["median_minutes"], 45.0)
        self.assertEqual(table["books"]["book_b"]["first_mover_count"], 0)
        self.assertEqual(table["ladder_medians_minutes"]["50%"], 10.0)
        self.assertIsNone(table["ladder_medians_minutes"]["75%"])

    def test_ladder_rungs_carry_their_own_n(self):
        # Each rung's median is a DIFFERENT subset (docs/RESEARCH_V3_TIMING.md
        # ADDENDUM 2, recommended item): the 25%/50% rungs are reached by
        # every event in this fixture, but 75%/100% are reached by none --
        # without ladder_ns, a reader cannot tell "10.0 minutes off 30
        # events" from "10.0 minutes off 1".
        table = leadlag.response_table(_fleet(30))
        self.assertEqual(table["ladder_ns"]["25%"], 30)
        self.assertEqual(table["ladder_ns"]["50%"], 30)
        self.assertEqual(table["ladder_ns"]["75%"], 0)
        self.assertEqual(table["ladder_ns"]["100%"], 0)

    def test_the_table_never_speaks_in_edges(self):
        table = leadlag.response_table(_fleet(30))
        self.assertIn("no entry here is an edge claim", table["note"])

    def test_stale_share_counts_events_not_books(self):
        events = _fleet(30)
        for event in events[:6]:
            event["stale_books"] = {
                "book_c": {"minutes": 20.0, "observations": 3,
                           "closed_by": "moved"},
                "book_d": {"minutes": 30.0, "observations": 4,
                           "closed_by": "first_pitch"}}
        table = leadlag.response_table(events)
        self.assertEqual(table["stale"]["events_with_a_stale_book"], 6)
        self.assertEqual(table["stale"]["share"], 0.2)
        self.assertEqual(table["stale"]["median_window_minutes"], 25.0)



class AppearanceTests(unittest.TestCase):
    def test_a_book_that_quoted_but_never_moved_still_counts_as_seen(self):
        """A book present pre-event in every window but never reacting must
        appear in the table (with its appearance count), not vanish -- its
        absence of movement IS the lead/lag finding about it."""
        events = [_event(first=("book_a",),
                         moves={"book_a": {"minutes": 5.0, "magnitude": 0.02}},
                         books=["book_a", "book_still"])
                  for _ in range(30)]
        table = leadlag.response_table(events)
        self.assertIn("book_still", table["books"])
        self.assertEqual(table["books"]["book_still"]["n"], 30)
        self.assertEqual(table["books"]["book_still"]["moved_n"], 0)

class StabilityTests(unittest.TestCase):
    def test_stable_leadership_overlaps_three(self):
        result = leadlag.leadership_stability(_fleet(40))
        self.assertEqual(result["overlap"],
                         len(set(result["first_half_top3"])
                             & set(result["second_half_top3"])))
        self.assertIn("book_a", result["first_half_top3"])
        self.assertIn("book_a", result["second_half_top3"])

    def test_a_leadership_flip_scores_low_overlap(self):
        events = _fleet(20, fast="book_a") + _fleet(20, fast="book_z")
        result = leadlag.leadership_stability(events)
        self.assertLessEqual(result["overlap"], 2)

    def test_thin_halves_refuse_to_judge_stability(self):
        self.assertIn("skipped", leadlag.leadership_stability(_fleet(20)))


if __name__ == "__main__":
    unittest.main()
