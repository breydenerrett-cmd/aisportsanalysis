"""The V3 measurement core, pinned against hand-computed fixtures.

Every quantity the pre-registration froze (docs/RESEARCH_V3_TIMING.md) is
computed here by hand on a small synthetic tape and asserted against the
module. The tape uses -110/-110 and simple round prices so each de-vigged
probability is an exact known value, the same trick the equivalence tests
use: a disagreement is logic, never float noise.
"""

import unittest

from src.research import eventstudy

EVENT = {"ts": "2026-08-30T20:00:00+00:00"}
START = "2026-08-30T23:00:00+00:00"

# -110/-110 de-vigs to exactly 0.5 either side; +100/-120 and friends give
# distinct, stable values -- what matters is the DELTA crossing 0.010.
EVEN = (-110, -110)
HOME_UP = (120, -140)     # home fair prob well above 0.5
HOME_UP_SMALL = (-108, -112)  # de-vigs to 0.50433: a 0.43pp nudge, under the floor


def _q(ts, book, pair):
    return {"ts": ts, "book": book,
            "away_price": pair[0], "home_price": pair[1]}


def _tape(pre_books=8, movers=(), stale=(), minutes=(5, 10, 15, 30, 60)):
    """Eight books quoted even pre-event; `movers` is {book: move_minute}."""
    quotes = []
    for i in range(pre_books):
        book = f"book_{i}"
        quotes.append(_q("2026-08-30T19:30:00+00:00", book, EVEN))
        for m in minutes:
            ts = f"2026-08-30T20:{m:02d}:00+00:00" if m < 60 \
                else "2026-08-30T21:00:00+00:00"
            moved = book in movers and m >= movers[book]
            quotes.append(_q(ts, book, HOME_UP if moved else EVEN))
    return quotes


class ExclusionTests(unittest.TestCase):
    def test_too_few_pre_event_books_excludes_the_event(self):
        result = eventstudy.measure(EVENT, _tape(pre_books=5))
        self.assertIn("only 5 books", result["excluded"])

    def test_an_event_after_first_pitch_is_excluded(self):
        result = eventstudy.measure(
            EVENT, _tape(), game_start="2026-08-30T19:00:00+00:00")
        self.assertEqual(result["excluded"], "event at or after first pitch")

    def test_a_stale_pre_quote_does_not_count_as_immediately_before(self):
        """Seven books quote 30 minutes before; one book's last quote is
        four hours old. That book must not be in the pre-event set."""
        quotes = _tape(pre_books=7)
        quotes.append(_q("2026-08-30T15:00:00+00:00", "ancient", EVEN))
        result = eventstudy.measure(EVENT, quotes)
        self.assertEqual(result["books_pre"], 7)

    def test_grade_c_shapes_are_refused_loudly(self):
        with self.assertRaises(eventstudy.EventStudyError):
            eventstudy.measure({"date": "2026-08-30"}, _tape())


class LatencyTests(unittest.TestCase):
    def test_the_ladder_reads_off_the_tape_exactly(self):
        # 8 books; movers at minutes 5,5,10,15,15,30 -- two never move.
        movers = {"book_0": 5, "book_1": 5, "book_2": 10, "book_3": 15,
                  "book_4": 15, "book_5": 30}
        result = eventstudy.measure(EVENT, _tape(movers=movers))
        self.assertIsNone(result["excluded"])
        ladder = result["ladder_minutes"]
        self.assertEqual(ladder["25%"], 5.0)    # 2 of 8
        self.assertEqual(ladder["50%"], 15.0)   # 4 of 8
        self.assertEqual(ladder["75%"], 30.0)   # 6 of 8
        self.assertIsNone(ladder["100%"])       # two books never moved

    def test_first_movers_tie_within_one_capture(self):
        movers = {"book_0": 5, "book_1": 5, "book_2": 10, "book_3": 10}
        result = eventstudy.measure(EVENT, _tape(movers=movers))
        self.assertEqual(result["first_movers"], ["book_0", "book_1"])
        self.assertEqual(result["first_move_minutes"], 5.0)

    def test_a_sub_floor_wobble_is_not_a_move(self):
        quotes = _tape(pre_books=8)
        quotes.append(_q("2026-08-30T20:05:00+00:00", "book_0", HOME_UP_SMALL))
        result = eventstudy.measure(EVENT, quotes)
        self.assertEqual(result["books_moved"], 0)
        self.assertEqual(result["first_movers"], [])

    def test_a_grade_b_interval_measures_from_its_end(self):
        event = {"interval": ("2026-08-30T19:45:00+00:00",
                              "2026-08-30T20:00:00+00:00")}
        movers = {"book_0": 5, "book_1": 5, "book_2": 5, "book_3": 5}
        result = eventstudy.measure(event, _tape(movers=movers))
        # From the interval END (20:00), not the start: 5 minutes, not 20.
        self.assertEqual(result["first_move_minutes"], 5.0)


class StaleTests(unittest.TestCase):
    def test_a_book_sitting_still_after_the_quorum_is_stale(self):
        # 6 of 8 move at minute 5 (quorum of 4 satisfied); book_6 moves at
        # 60; book_7 never moves and rides to first pitch.
        movers = {f"book_{i}": 5 for i in range(6)}
        movers["book_6"] = 60
        result = eventstudy.measure(EVENT, _tape(movers=movers),
                                    game_start=START)
        self.assertIn("book_6", result["stale_books"])
        self.assertEqual(result["stale_books"]["book_6"]["closed_by"], "moved")
        self.assertEqual(result["stale_books"]["book_6"]["minutes"], 55.0)
        self.assertIn("book_7", result["stale_books"])
        self.assertEqual(result["stale_books"]["book_7"]["closed_by"],
                         "first_pitch")

    def test_no_quorum_means_no_stale_claims_at_all(self):
        movers = {"book_0": 5}   # 1 of 8 is under the 50% quorum
        result = eventstudy.measure(EVENT, _tape(movers=movers))
        self.assertEqual(result["stale_books"], {})


class DirectionTests(unittest.TestCase):
    def test_agreement_with_the_frozen_expected_sign(self):
        movers = {f"book_{i}": 5 for i in range(6)}
        result = eventstudy.measure(EVENT, _tape(movers=movers),
                                    expected_sign=+1)
        self.assertTrue(result["direction"]["first_move_agrees"])
        self.assertTrue(result["direction"]["consensus_agrees"])
        against = eventstudy.measure(EVENT, _tape(movers=movers),
                                     expected_sign=-1)
        self.assertFalse(against["direction"]["first_move_agrees"])

    def test_no_frozen_direction_means_no_agreement_claim(self):
        result = eventstudy.measure(EVENT, _tape())
        self.assertIsNone(result["direction"])

    def test_a_sub_floor_consensus_move_declines_to_agree_or_disagree(self):
        movers = {"book_0": 5}   # one mover barely shifts the 8-book mean
        result = eventstudy.measure(EVENT, _tape(movers=movers),
                                    expected_sign=+1)
        self.assertIsNone(result["direction"]["consensus_agrees"])


if __name__ == "__main__":
    unittest.main()
