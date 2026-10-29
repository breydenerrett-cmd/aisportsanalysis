"""Pick grades: confidence and value for a pick, from the hound's own record settled before the pick was placed.

What is pinned, and the story behind each pin (docs: the module docstring of ``src/hounds/pick_grades.py``):

  * POINT IN TIME. A pick sees only bets settled strictly before it was placed. A bet settled later, a bet settled at the very
    same instant, and a corrupt bet "settled" before it was placed never move a grade. This is the property that lets a grade
    be computed on read and never stored.
  * SHRINKAGE. A 3-0 start in a spot must not read as Value. The ruling asked for 20 pseudo bets of shrinkage; at 20 a 3-0
    start scored 81, so the constant is 150 and this file pins the result the ruling actually wanted.
  * THE SPOT FALLS BACK from specific to broad until a spot has enough bets, and says "thin" when none does.
  * A push or a void is not a bet that won or lost.
  * NO HISTORY IS "Not yet available", never a zero bar; a missing price or placement time says so too.
  * The wording never says "edge", "lock", "profit" or promises anything, and the confidence sentence always says it is
    not a win chance.
"""

from __future__ import annotations

import random
import re
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.hounds import pick_grades as pg

T0 = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


def stamp(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def bet(i, result, *, price=-110, sport="nhl", market="totals", day=None, settle_hours=6, books=8, clv=None, lock=None,
        graded="auto", bet_id=None):
    """One ledger bet placed on day ``i`` (or ``day``) of October, settled ``settle_hours`` later (``None``: still open)."""
    placed = lock if lock is not None else T0 + timedelta(days=i if day is None else day)
    if graded == "auto":
        graded = None if result is None or settle_hours is None else stamp(placed + timedelta(hours=settle_hours))
    return {"bet_id": bet_id or f"b{i}", "price_average": price, "sport": sport, "market": market, "result": result,
            "lock_utc": stamp(placed), "graded_utc": graded, "n_books": books, "clv_pts": clv}


def record(n_win, n_loss, **kw):
    """A hound that won ``n_win`` and lost ``n_loss`` in a fixed shuffled order, one bet a day from the first."""
    results = ["win"] * n_win + ["loss"] * n_loss
    random.Random(7).shuffle(results)
    return [bet(i, r, **kw) for i, r in enumerate(results)]


def pick_after(rows, **kw):
    """An open pick placed the day after the last of ``rows``."""
    day = len(rows) + 1
    return bet(day, None, bet_id="pick", **kw)


class PointInTime(unittest.TestCase):
    def setUp(self):
        self.history = record(6, 4)
        self.pick = pick_after(self.history)

    def grade(self, rows):
        return pg.grade_bets(rows)["pick"]

    def test_a_bet_settled_after_the_pick_was_placed_changes_nothing(self):
        before = self.grade(self.history + [self.pick])
        later = bet(30, "win", bet_id="later", lock=T0 + timedelta(days=2), settle_hours=24 * 40)
        self.assertEqual(before, self.grade(self.history + [self.pick, later]))
        # and a whole run of later wins does not either
        wins = [bet(40 + i, "win", bet_id=f"w{i}") for i in range(30)]
        self.assertEqual(before, self.grade(self.history + [self.pick] + wins))

    def test_a_bet_settled_before_the_pick_was_placed_does_count(self):
        before = self.grade(self.history + [self.pick])
        earlier = bet(0, "win", bet_id="earlier", lock=T0 - timedelta(days=3))
        after = self.grade(self.history + [self.pick, earlier])
        self.assertEqual(after["value"]["slice"]["n"], before["value"]["slice"]["n"] + 1)
        self.assertEqual(after["value"]["slice"]["w"], before["value"]["slice"]["w"] + 1)

    def test_a_bet_settled_at_the_very_instant_of_placement_is_not_history(self):
        placed = datetime.fromisoformat(self.pick["lock_utc"].replace("Z", "+00:00"))
        tie = bet(0, "win", bet_id="tie", lock=placed - timedelta(days=1), graded=stamp(placed))
        self.assertEqual(self.grade(self.history + [self.pick]), self.grade(self.history + [self.pick, tie]))

    def test_a_bet_without_a_settle_time_is_not_history(self):
        no_stamp = bet(1, "win", bet_id="nostamp", lock=T0 - timedelta(days=2), graded=None)
        self.assertEqual(self.grade(self.history + [self.pick]), self.grade(self.history + [self.pick, no_stamp]))

    def test_a_corrupt_bet_settled_before_it_was_placed_is_not_history(self):
        placed = T0 - timedelta(days=2)
        corrupt = bet(0, "win", bet_id="corrupt", lock=placed, graded=stamp(placed - timedelta(days=5)))
        self.assertEqual(self.grade(self.history + [self.pick]), self.grade(self.history + [self.pick, corrupt]))

    def test_the_pick_never_counts_toward_its_own_grade(self):
        settled = dict(self.pick, result="win", graded_utc=stamp(T0 + timedelta(days=60)))
        self.assertEqual(self.grade(self.history + [self.pick])["value"], self.grade(self.history + [settled])["value"])

    def test_every_pick_in_a_run_is_graded_from_its_own_past(self):
        grades = pg.grade_bets(self.history)
        ns = [grades[f"b{i}"]["value"]["slice"] for i in range(len(self.history))]
        counts = [0 if s is None else s["n"] for s in ns]
        # bet i is placed on day i and each is settled six hours after: bet i sees exactly the i bets before it
        self.assertEqual(counts, list(range(len(self.history))))

    def test_an_open_pick_has_no_clv_a_settled_one_does(self):
        rows = [bet(0, "win", clv=1.3), bet(1, "loss", clv=-0.7), bet(2, "win", clv=None), bet(3, "push", clv=0.0),
                bet(4, None, bet_id="open")]
        grades = pg.grade_bets(rows)
        self.assertIsNone(grades["open"]["clv"])
        self.assertEqual(grades["b0"]["clv"], {"pts": 1.3, "label": "Beat the close"})
        self.assertEqual(grades["b1"]["clv"], {"pts": -0.7, "label": "Missed the close"})
        self.assertEqual(grades["b2"]["clv"], {"pts": None, "label": "Not measured"})
        self.assertEqual(grades["b3"]["clv"], {"pts": 0.0, "label": "Matched the close"})


class Shrinkage(unittest.TestCase):
    def test_a_three_and_oh_start_stays_near_fair(self):
        for price in (-110, 150, 300, 1000):
            rows = [bet(i, "win", price=price) for i in range(3)]
            score = pg.grade_bets(rows + [pick_after(rows, price=price)])["pick"]["value"]["score"]
            self.assertLess(abs(score - 50), 10, f"3-0 at {price} scored {score}")

    def test_a_long_run_ahead_of_its_prices_reads_as_value_and_behind_as_overpriced(self):
        ahead = record(70, 30)
        behind = record(30, 70)
        self.assertEqual(pg.grade_bets(ahead + [pick_after(ahead)])["pick"]["value"]["label"], "Value")
        self.assertEqual(pg.grade_bets(behind + [pick_after(behind)])["pick"]["value"]["label"], "Overpriced")

    def test_the_score_is_held_to_the_dial(self):
        wins = [bet(i, "win", price=300) for i in range(600)]
        score = pg.grade_bets(wins + [pick_after(wins, price=300)])["pick"]["value"]["score"]
        self.assertEqual(score, 100)
        losses = [bet(i, "loss", price=-110) for i in range(600)]
        self.assertEqual(pg.grade_bets(losses + [pick_after(losses)])["pick"]["value"]["score"], 0)

    def test_the_numbers_behind_a_grade_are_the_formula(self):
        rows = record(16, 7)                      # the owner's hound: 16-7 at -110
        value = pg.grade_bets(rows + [pick_after(rows)])["pick"]["value"]
        implied = 1 / (1 + 100 / 110)
        expected = 23 * implied
        excess = (16 - expected) / (23 + pg.VALUE_SHRINK_BETS)
        self.assertAlmostEqual(value["implied"], implied, places=4)
        self.assertAlmostEqual(value["shrunk_rate"], implied + excess, places=4)
        self.assertEqual(value["score"], int(50 + excess * 100 * 5 + 0.5))
        self.assertEqual(value["slice"], {"name": "NHL totals, near even, favourite", "n": 23, "w": 16, "l": 7,
                                          "expected_w": round(expected, 1)})
        self.assertEqual(value["reason"], "Its NHL totals, near even, favourite: 16-7. -110 implies 52%; its record shrinks to 55%.")


class TheSpotFallsBack(unittest.TestCase):
    def test_the_most_specific_spot_with_enough_bets_wins(self):
        rows = record(5, 3)                                       # 8 NHL totals near even favourites
        slice_ = pg.grade_bets(rows + [pick_after(rows)])["pick"]["value"]["slice"]
        self.assertEqual((slice_["name"], slice_["n"]), ("NHL totals, near even, favourite", 8))

    def test_too_few_in_the_narrow_spot_falls_to_a_broader_one(self):
        narrow = [bet(i, "win" if i % 2 else "loss") for i in range(5)]                      # 5 NHL totals near even
        moneylines = [bet(10 + i, "win" if i % 2 else "loss", market="h2h", price=-130) for i in range(4)]   # + 4 NHL favourites
        rows = narrow + moneylines
        pick = bet(30, None, bet_id="pick")
        value = pg.grade_bets(rows + [pick])["pick"]["value"]
        self.assertEqual(value["slice"]["name"], "NHL favourites")      # sport + favourite-or-underdog: 9 bets
        self.assertEqual(value["slice"]["n"], 9)

    def test_the_spot_is_not_chosen_across_a_different_sport_or_side(self):
        other = [bet(i, "win", sport="mlb", price=130) for i in range(9)]                    # 9 MLB underdogs, all wins
        mine = [bet(10 + i, "loss") for i in range(2)]
        value = pg.grade_bets(other + mine + [bet(30, None, bet_id="pick")])["pick"]["value"]
        # sport and side both differ from the 9 wins, so only the broadest spot (every bet) can pool them
        self.assertEqual(value["slice"]["name"], "bets so far")
        self.assertEqual(value["slice"]["n"], 11)

    def test_when_no_spot_reaches_the_minimum_the_broadest_is_used_and_called_thin(self):
        rows = [bet(0, "win"), bet(1, "win", sport="mlb", market="h2h", price=140), bet(2, "loss", price=-150)]
        value = pg.grade_bets(rows + [bet(10, None, bet_id="pick")])["pick"]["value"]
        self.assertEqual(value["slice"]["name"], "bets so far")
        self.assertEqual(value["slice"]["n"], 3)
        self.assertIn("(thin)", value["reason"])
        confidence = pg.grade_bets(rows + [bet(10, None, bet_id="pick")])["pick"]["confidence"]
        self.assertIn("(thin)", confidence["reason"])
        self.assertIn("earlier bets", confidence["reason"])

    def test_a_row_missing_its_sport_still_counts_in_the_broader_spots(self):
        rows = [dict(bet(i, "win" if i % 3 else "loss"), sport=None, market=None) for i in range(9)]
        value = pg.grade_bets(rows + [dict(bet(20, None, bet_id="pick"), sport=None, market=None)])["pick"]["value"]
        self.assertEqual(value["slice"]["name"], "favourites")
        self.assertEqual(value["slice"]["n"], 9)

    def test_the_band_names_follow_the_price(self):
        for price, name in ((-175, "NHL totals, short favourites"), (-130, "NHL totals, favourites"),
                            (105, "NHL totals, near even, underdog"), (150, "NHL totals, underdogs"),
                            (350, "NHL totals, long shots")):
            rows = [bet(i, "win" if i % 2 else "loss", price=price) for i in range(8)]
            slice_ = pg.grade_bets(rows + [pick_after(rows, price=price)])["pick"]["value"]["slice"]
            self.assertEqual(slice_["name"], name, price)


class PushesAreNotBets(unittest.TestCase):
    def test_pushes_and_voids_are_left_out_of_every_count(self):
        rows = record(6, 2) + [bet(20 + i, r) for i, r in enumerate(["push", "push", "void"])]
        value = pg.grade_bets(rows + [bet(40, None, bet_id="pick")])["pick"]["value"]
        self.assertEqual((value["slice"]["n"], value["slice"]["w"], value["slice"]["l"]), (8, 6, 2))

    def test_a_settled_push_still_gets_its_own_clv(self):
        rows = [bet(0, "push", clv=0.4)]
        self.assertEqual(pg.grade_bets(rows)["b0"]["clv"], {"pts": 0.4, "label": "Beat the close"})

    def test_a_history_of_only_pushes_is_no_history(self):
        rows = [bet(i, "push") for i in range(5)]
        grades = pg.grade_bets(rows + [bet(10, None, bet_id="pick")])["pick"]
        self.assertEqual(grades["value"]["label"], "Not yet available")


class NoHistoryIsNotAZero(unittest.TestCase):
    def test_the_first_ever_pick_is_not_yet_available_on_both_meters(self):
        grades = pg.grade_bets([bet(0, None, bet_id="pick")])["pick"]
        for meter in ("value", "confidence"):
            self.assertIsNone(grades[meter]["score"])
            self.assertEqual(grades[meter]["label"], "Not yet available")
            self.assertEqual(grades[meter]["reason"], "No settled bets like this before it was placed.")
        self.assertIsNone(grades["value"]["slice"])
        self.assertIsNone(grades["confidence"]["parts"])

    def test_a_pick_with_no_price_says_so(self):
        grades = pg.grade_bets(record(5, 5) + [dict(bet(20, None, bet_id="pick"), price_average=None)])["pick"]
        self.assertEqual(grades["value"]["label"], "Not yet available")
        self.assertIn("no recorded board price", grades["value"]["reason"])

    def test_a_pick_with_no_placement_time_is_not_graded_against_a_guess(self):
        grades = pg.grade_bets(record(5, 5) + [dict(bet(20, None, bet_id="pick"), lock_utc=None)])["pick"]
        self.assertEqual(grades["confidence"]["label"], "Not yet available")
        self.assertIn("not recorded", grades["confidence"]["reason"])

    def test_a_history_bet_with_no_price_is_not_history(self):
        base = record(6, 3)
        priceless = [dict(b, price_average=None, bet_id=f"p{i}") for i, b in enumerate(record(3, 0))]
        a = pg.grade_bets(base + [pick_after(base)])["pick"]
        b = pg.grade_bets(base + priceless + [pick_after(base)])["pick"]
        self.assertEqual(a["value"], b["value"])

    def test_the_price_is_the_board_average_not_the_best_quote(self):
        # `price` on the public BetRow is the best quote; the grade reads `price_average` (the price the record is graded at)
        rows = [dict(b, price=900) for b in record(5, 3)]
        value = pg.grade_bets(rows + [dict(pick_after(rows), price=900)])["pick"]["value"]
        self.assertAlmostEqual(value["implied"], 0.5238, places=3)


class Confidence(unittest.TestCase):
    def test_the_parts_and_weights(self):
        rows = record(16, 7)
        conf = pg.grade_bets(rows + [pick_after(rows, books=6)])["pick"]["confidence"]
        self.assertEqual(conf["parts"]["sample"], round(100 * 23 / 43))
        self.assertEqual(conf["parts"]["market"], 50)                 # 6 books: halfway between 3 and 9
        implied = 1 / (1 + 100 / 110)
        z = (16 - 23 * implied) / (23 * implied * (1 - implied)) ** 0.5
        self.assertEqual(conf["parts"]["consistency"], round(100 * min(z / 2, 1)))
        want = 0.5 * conf["parts"]["sample"] + 0.3 * conf["parts"]["consistency"] + 0.2 * conf["parts"]["market"]
        self.assertAlmostEqual(conf["score"], want, delta=0.51)

    def test_a_record_behind_its_prices_earns_no_consistency(self):
        rows = record(3, 9)
        conf = pg.grade_bets(rows + [pick_after(rows)])["pick"]["confidence"]
        self.assertEqual(conf["parts"]["consistency"], 0)
        self.assertIn("behind the prices", conf["reason"])

    def test_the_books_part_runs_from_three_to_nine(self):
        for books, part in ((None, None), (1, 0), (3, 0), (4, 17), (6, 50), (9, 100), (14, 100)):
            rows = record(5, 3)
            conf = pg.grade_bets(rows + [pick_after(rows, books=books)])["pick"]["confidence"]
            self.assertEqual(conf["parts"]["market"], part, books)

    def test_a_pick_with_no_book_count_leaves_the_part_out_instead_of_scoring_it_zero(self):
        rows = record(16, 7)
        with_books = pg.grade_bets(rows + [pick_after(rows, books=9)])["pick"]["confidence"]
        without = pg.grade_bets(rows + [pick_after(rows, books=None)])["pick"]["confidence"]
        self.assertIsNone(without["parts"]["market"])
        want = (0.5 * with_books["parts"]["sample"] + 0.3 * with_books["parts"]["consistency"]) / 0.8
        self.assertAlmostEqual(without["score"], want, delta=0.51)
        self.assertIn("not recorded", without["reason"])

    def test_variance_that_rounds_to_nothing_does_not_divide_by_zero(self):
        rows = [bet(i, "win", price=-10 ** 15) for i in range(9)]       # every bet "certain": no variance to measure a z from
        conf = pg.grade_bets(rows + [pick_after(rows, price=-10 ** 15)])["pick"]["confidence"]
        self.assertEqual(conf["parts"]["consistency"], 0)
        self.assertIn("about level", conf["reason"])

    def test_the_sentence_always_says_it_is_not_a_win_chance(self):
        rows = record(16, 7)
        sentence = pg.grade_bets(rows + [pick_after(rows)])["pick"]["confidence"]["reason"]
        self.assertTrue(sentence.endswith("Not a win chance."))
        self.assertIn("23 similar bets", sentence)
        self.assertIn("ahead of the prices", sentence)
        self.assertIn("8 books quoted it", sentence)


class Labels(unittest.TestCase):
    def test_value_labels_at_the_thresholds(self):
        for score, label in ((0, "Overpriced"), (39, "Overpriced"), (40, "Fair"), (50, "Fair"), (60, "Fair"), (61, "Value"),
                             (100, "Value")):
            self.assertEqual(pg._value_label(score), label, score)

    def test_confidence_labels_at_the_thresholds(self):
        for score, label in ((0, "Low"), (34, "Low"), (35, "Medium"), (65, "Medium"), (66, "High"), (100, "High")):
            self.assertEqual(pg._confidence_label(score), label, score)

    def test_the_label_always_agrees_with_the_whole_number_shown(self):
        # a score of 60.4 is shown as 60 and must be called Fair, never Value
        for wins in range(0, 41):
            rows = record(wins, 40 - wins)
            for meter, fn in (("value", pg._value_label), ("confidence", pg._confidence_label)):
                got = pg.grade_bets(rows + [pick_after(rows)])["pick"][meter]
                self.assertIsInstance(got["score"], int)
                self.assertEqual(got["label"], fn(got["score"]))

    def test_the_price_bands_are_the_apps_own(self):
        from src.hounds.interact import training
        self.assertEqual(pg.PRICE_BANDS, training.PRICE_BANDS)


class DeterministicAndCheap(unittest.TestCase):
    def test_same_rows_same_grades_in_any_order(self):
        rows = record(30, 20) + [pick_after(record(30, 20))]
        shuffled = rows[:]
        random.Random(1).shuffle(shuffled)
        self.assertEqual(pg.grade_bets(rows), pg.grade_bets(rows))
        self.assertEqual(pg.grade_bets(rows), pg.grade_bets(shuffled))

    def test_the_rows_are_not_changed(self):
        rows = record(8, 4)
        copy = [dict(r) for r in rows]
        pg.grade_bets(rows)
        self.assertEqual(rows, copy)

    def test_five_thousand_bets_grade_in_well_under_a_second(self):
        rng = random.Random(3)
        rows = [bet(i, rng.choice(["win", "loss"]), price=rng.choice([-130, -110, 105, 140]),
                    sport=rng.choice(["nhl", "nba", "mlb"]), market=rng.choice(["h2h", "totals", "spreads"]))
                for i in range(5000)]
        started = time.perf_counter()
        grades = pg.grade_bets(rows)
        self.assertLess(time.perf_counter() - started, 1.5)
        self.assertEqual(len(grades), 5000)


class TheWordsStayHonest(unittest.TestCase):
    BANNED = re.compile(r"\b(edge|lock|locks|locked|profit|guarantee|beta|sure thing|free money)\b", re.I)

    def test_no_sentence_makes_a_claim(self):
        seen = []
        for wins in (0, 3, 9, 16, 23):
            rows = record(wins, 23 - wins)
            grades = pg.grade_bets(rows + [pick_after(rows), bet(99, None, bet_id="first", lock=T0 - timedelta(days=9))])
            for key in ("pick", "first"):
                for meter in ("value", "confidence"):
                    seen.append(grades[key][meter]["reason"])
        self.assertGreater(len(seen), 5)
        for sentence in seen:
            self.assertIsNone(self.BANNED.search(sentence), sentence)


class FromBetRows(unittest.TestCase):
    """The glue that reads the public ``BetRow`` objects."""

    def row(self, i, result, **kw):
        placed = T0 + timedelta(days=i)
        fields = dict(hound_id="h", date=f"2026-10-{i + 1:02d}", event_id=f"e{i}", game=f"g{i}", market="totals",
                      selection=f"Over {i}", line="8.5", price=-105, price_average=-110, sport="nhl", result=result,
                      segment="forward", lock_utc=stamp(placed), recorded_utc=stamp(placed + timedelta(minutes=5)),
                      graded_utc=None if result is None else stamp(placed + timedelta(hours=6)), book_count=7, clv_pts=None)
        fields.update(kw)
        return SimpleNamespace(**fields)

    def test_a_page_is_graded_from_the_whole_history_not_from_the_page(self):
        history = [self.row(i, "win" if i % 2 else "loss") for i in range(12)] + [self.row(12, None)]
        page = [history[-1]]
        grades = pg.grades_for_page(history, page)
        self.assertEqual(grades[0]["value"]["slice"]["n"], 12)

    def test_a_replay_ticket_is_neither_graded_nor_history(self):
        history = [self.row(i, "win", segment="replay") for i in range(10)] + [self.row(10, None)]
        grades = pg.grades_for_page(history, [history[0], history[-1]])
        self.assertIsNone(grades[0])
        self.assertEqual(grades[1]["value"]["label"], "Not yet available")

    def test_a_ticket_without_a_lock_stamp_falls_back_to_when_it_was_recorded(self):
        history = [self.row(i, "win" if i % 2 else "loss", lock_utc=None) for i in range(10)] + [self.row(10, None, lock_utc=None)]
        grades = pg.grades_for_page(history, [history[-1]])
        self.assertEqual(grades[0]["value"]["slice"]["n"], 10)

    def test_the_bet_uses_the_average_price_and_the_book_count_of_the_row(self):
        history = [self.row(i, "win" if i % 2 else "loss") for i in range(10)] + [self.row(10, None)]
        grade = pg.grades_for_page(history, [history[-1]])[0]
        self.assertAlmostEqual(grade["value"]["implied"], 0.5238, places=3)
        self.assertEqual(grade["confidence"]["parts"]["market"], 67)         # 7 books


if __name__ == "__main__":
    unittest.main()
