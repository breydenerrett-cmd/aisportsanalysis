"""The battery-validation matrix: is the amended battery a GENERAL skeptic?

The falsification battery was born from one autopsy (M3), and a battery built
from one corpse risks being a machine tuned to kill that corpse and nothing
else -- or worse, to kill everything that is not that corpse. This module runs
six controlled candidates through the battery, each constructed so that ONE
property is present and everything else is clean:

  1. a uniform genuine effect        -> must survive
  2. a monotonic dose-response       -> must survive
  3. a one-book artifact             -> book_concentration must kill it
  4. a spike with a sparse upper tail-> dose_response must kill it
     (with conservatism companions: doubt BELOW still protects, and a
     supported upper band still rescues)
  5. a sign-flipping effect          -> season_split must kill it
  6. pure null noise                 -> nothing may fire

Plus a hygiene check that no fatal rule's source mentions M3 or any real
sportsbook or team, and that the rule set is versioned and fingerprinted.

Every row set is deterministic: exact win counts at implied 0.5, cycles chosen
coprime so books/teams/doses stay balanced by construction, one or two rows
per date so date-clustering cannot destroy a real construction's significance.
If a case fails here, the battery is wrong or the case is misjudged -- the fix
is never to soften the assertion.
"""

import datetime as dt
import inspect
import re
import unittest

from src.research import battery


def _dates(start, count):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(count)]


def _uniform_effect_rows():
    """420 rows, 65% wins at implied 0.5, one row per date.

    Cycle lengths are coprime with the win pattern's period (20): 7 books,
    21 teams, 3 doses. Over 420 rows every book carries exactly 39/60 wins,
    every team 13/20, every dose 91/140 -- the effect is IDENTICAL in every
    slice by construction, so any fatal verdict is the battery's error."""
    rows = []
    idx = 0
    for year in (2023, 2024):
        for date in _dates(dt.date(year, 4, 1), 210):
            rows.append({
                "date": date,
                "won": (idx % 20) < 13,
                "implied": 0.5,
                "season": year,
                "team": f"team_{idx % 21:02d}",
                "book": f"book_{idx % 7}",
                "dose": 0.02 + 0.005 * (idx % 3),
            })
            idx += 1
    return rows


def _marginal_uniform_rows():
    """A uniform 55% effect at the edge of significance, with one big book.

    460 rows, one per date, every book winning exactly 11 of each 20. The big
    book holds 260 rows, so leaving it out drops the sample enough that the
    clustered p crosses LOO_P_CEILING through SAMPLE SIZE ALONE while the
    effect stays exactly where it was. This is the precise situation the
    shrinkage leg exists to forgive: significance lost, size kept."""
    rows = []
    dates = iter(_dates(dt.date(2024, 3, 1), 460))
    for book, size in (("book_big", 260), ("book_a", 40), ("book_b", 40),
                       ("book_c", 40), ("book_d", 40), ("book_e", 40)):
        for i in range(size):
            rows.append({"date": next(dates), "won": (i % 20) < 11,
                         "implied": 0.5, "book": book})
    return rows


def _banded_dose_rows(band_specs, start=dt.date(2024, 4, 1)):
    """(dose, wins, losses) per intended band, one row per date."""
    rows = []
    dates = iter(_dates(start, sum(w + l for _, w, l in band_specs)))
    for dose, wins, losses in band_specs:
        for i in range(wins + losses):
            rows.append({"date": next(dates), "won": i < wins,
                         "implied": 0.5, "dose": dose})
    return rows


def _one_book_artifact_rows():
    """One book wins everything; four others are exact coin flips.

    Neutral fake names on purpose: the battery must kill the SHAPE, and a test
    that only works with a real book's name would prove the opposite."""
    rows = []
    dates = iter(_dates(dt.date(2024, 5, 1), 80))
    for _ in range(40):
        rows.append({"date": next(dates), "won": True, "implied": 0.5,
                     "book": "book_f"})
    for name in ("book_a", "book_b", "book_c", "book_d"):
        for i in range(10):
            rows.append({"date": next(dates), "won": i % 2 == 0,
                         "implied": 0.5, "book": name})
    return rows


def _null_rows():
    """480 rows, 240 dates, one win and one loss per date: effect exactly 0.

    Book, team and dose are assigned per DATE so every slice is perfectly
    balanced -- 50% everywhere, in both seasons, at every dose. There is no
    construction more innocent than this one."""
    rows = []
    d = 0
    for year in (2023, 2024):
        for date in _dates(dt.date(year, 4, 1), 120):
            for won in (True, False):
                rows.append({
                    "date": date, "won": won, "implied": 0.5,
                    "season": year,
                    "team": f"team_{d % 10}",
                    "book": f"book_{d % 6}",
                    "dose": 0.02 + 0.005 * (d % 3),
                })
            d += 1
    return rows


class UniformGenuineEffectTests(unittest.TestCase):
    """Case 1: an effect that is everywhere must not die anywhere."""

    def test_a_uniform_strong_effect_survives_every_fatal_rule(self):
        result = battery.run(_uniform_effect_rows(), dose_key="dose")
        self.assertTrue(result["ran"])
        self.assertEqual(result["fatal"], [])
        self.assertTrue(result["survives"])
        self.assertAlmostEqual(result["report"]["baseline"]["effect"], 0.15)

    def test_the_shrinkage_leg_forgives_pure_sample_size_significance_loss(self):
        # The amendment's core promise: a marginally significant UNIFORM
        # effect whose leave-one-out p crosses the ceiling only because the
        # sample shrank must NOT be called concentrated, because its effect
        # size did not move. Before the shrinkage leg was stated this shape
        # was the false-kill risk of rule 3.
        result = battery.run(_marginal_uniform_rows())
        check = result["report"]["book_concentration"]
        self.assertLessEqual(check["full"]["p"], battery.FULL_P_LINE)
        loo = check["leave_one_out"]["book_big"]
        self.assertGreater(loo["p"], battery.LOO_P_CEILING)
        self.assertGreaterEqual(
            loo["effect"], battery.LOO_SHRINKAGE * check["full"]["effect"])
        self.assertFalse(check["fatal"])
        self.assertEqual(result["fatal"], [])
        self.assertTrue(result["survives"])


class GenuineDoseResponseTests(unittest.TestCase):
    """Case 2: more dose, more effect -- the one shape rule 5 must spare."""

    def test_a_monotonic_dose_response_is_not_fatal(self):
        # Sub-threshold band flat at zero, then +4pp, +8pp, +12pp. The spike
        # (first band over the floor) sits on a <=0 band, so the amended rule
        # goes looking for support above -- and both upper bands carry far
        # more than SPIKE_SUPPORT_FRACTION of the spike. A real gradient.
        graded = _banded_dose_rows([
            (0.010, 20, 20),   # sub-threshold: 0pp
            (0.021, 27, 23),   # +4pp -- the spike band
            (0.027, 29, 21),   # +8pp
            (0.033, 31, 19),   # +12pp
        ])
        selected = [r for r in graded if r["dose"] >= 0.02]
        result = battery.run(selected, dose_key="dose",
                             dose_bands=[0.0, 0.02, 0.025, 0.03, 0.04],
                             dose_rows=graded)
        self.assertNotIn("dose_response", result["fatal"])
        self.assertIn("not ruled out", result["report"]["dose_response"]["note"])
        self.assertEqual(result["fatal"], [])
        self.assertTrue(result["survives"])


class ConcentratedArtifactTests(unittest.TestCase):
    """Case 3: significance that lives in one unit is a story, not an effect."""

    def test_one_book_carrying_all_significance_is_fatal(self):
        result = battery.run(_one_book_artifact_rows())
        check = result["report"]["book_concentration"]
        # The artifact really does look like a result on the full sample.
        self.assertLessEqual(check["full"]["p"], 0.05)
        self.assertIn("book_concentration", result["fatal"])
        self.assertEqual(check["killed_by"], ["book_f"])
        # Every other book is an exact coin flip, so nothing else fires.
        self.assertEqual(result["fatal"], ["book_concentration"])
        self.assertFalse(result["survives"])


class SparseUpperTailTests(unittest.TestCase):
    """Case 4: the amended asymmetry -- doubt below protects, doubt above
    does not rescue. Both directions get their own test, because a battery
    that got the asymmetry backwards would pass a single-direction test."""

    def test_a_spike_over_a_judgeable_contradiction_with_a_sparse_tail_is_fatal(self):
        # 40 judgeable rows below the spike at -2.5pp, a +30pp spike, and
        # only 10 rows above it. Under the amended rule an unjudgeable upper
        # tail is not a gradient: the burden shifted to the candidate the
        # moment the band below judged against it.
        graded = _banded_dose_rows([
            (0.010, 19, 21),   # judgeable, <= 0: the contradiction
            (0.021, 32, 8),    # the spike
            (0.027, 5, 5),     # 10 rows: too sparse to judge
        ])
        selected = [r for r in graded if r["dose"] >= 0.02]
        result = battery.run(selected, dose_key="dose",
                             dose_bands=[0.0, 0.02, 0.025, 0.03],
                             dose_rows=graded)
        self.assertEqual(result["fatal"], ["dose_response"])
        self.assertIn("spike signature",
                      result["report"]["dose_response"]["note"])

    def test_an_unjudgeable_band_below_the_spike_still_protects(self):
        # Same spike, same sparse tail, but the BELOW band has only 10 rows.
        # The kill needs positive evidence against; ten rows are doubt, and
        # doubt below the spike must stay non-fatal or the battery would be
        # killing candidates for the caller's thin grading.
        graded = _banded_dose_rows([
            (0.010, 5, 5),     # below the row floor: doubt, not evidence
            (0.021, 32, 8),    # the spike
            (0.027, 5, 5),
        ])
        selected = [r for r in graded if r["dose"] >= 0.02]
        result = battery.run(selected, dose_key="dose",
                             dose_bands=[0.0, 0.02, 0.025, 0.03],
                             dose_rows=graded)
        self.assertNotIn("dose_response", result["fatal"])
        self.assertIn("in doubt, non-fatal",
                      result["report"]["dose_response"]["note"])

    def test_a_judgeable_supported_upper_band_rescues_the_spike(self):
        # The contradiction below is judged, but a judgeable band above the
        # spike carries more than half its effect (+17.5pp vs +30pp): the
        # gradient the rule demands is shown, so the candidate lives.
        graded = _banded_dose_rows([
            (0.010, 20, 20),   # judgeable, exactly 0
            (0.021, 32, 8),    # the spike: +30pp
            (0.027, 27, 13),   # +17.5pp >= half the spike
        ])
        selected = [r for r in graded if r["dose"] >= 0.02]
        result = battery.run(selected, dose_key="dose",
                             dose_bands=[0.0, 0.02, 0.025, 0.03],
                             dose_rows=graded)
        self.assertNotIn("dose_response", result["fatal"])
        self.assertIn("not ruled out",
                      result["report"]["dose_response"]["note"])


class SignFlippingEffectTests(unittest.TestCase):
    """Case 5: an effect that points both ways across seasons is a year."""

    def test_opposite_signed_judgeable_seasons_are_fatal(self):
        # +15pp in 2023, -5pp in 2024, both well past the floor and both
        # judgeable. Magnitudes deliberately asymmetric so the overall
        # baseline stays positive and no OTHER rule fires: the kill must
        # come from season_split alone or the test proves nothing about it.
        rows = []
        for i, date in enumerate(_dates(dt.date(2023, 4, 1), 60)):
            rows.append({"date": date, "won": (i % 20) < 13,
                         "implied": 0.5, "season": 2023})
        for i, date in enumerate(_dates(dt.date(2024, 4, 1), 60)):
            rows.append({"date": date, "won": (i % 20) < 9,
                         "implied": 0.5, "season": 2024})
        result = battery.run(rows)
        self.assertEqual(result["fatal"], ["season_split"])
        self.assertFalse(result["survives"])
        seasons = result["report"]["season_split"]["seasons"]
        self.assertGreater(seasons["2023"]["effect"], 0.01)
        self.assertLess(seasons["2024"]["effect"], -0.01)


class PureNullTests(unittest.TestCase):
    """Case 6: the control group -- what the battery says about nothing.

    Two properties matter, and they are different. First, NO SHAPE RULE may
    fire: season_split, extreme_removal and dose_response each claim to have
    recognised a specific pattern, and recognising a pattern in exactly-zero,
    perfectly-balanced data would make their kills on real candidates
    uninterpretable. Second, the null must NEVER be endorsed: this battery
    destroys and does not confirm, so an exact null coming out
    survives=True-and-meaningful would be the worse failure.

    The concentration checks DO fire here, by the pre-registered leg (i):
    an effect under the floor that cannot hold significance through
    leave-one-out "was never a market-wide effect" -- and a zero effect is
    the limiting case of exactly that. The old (pre-amendment) battery
    returns the identical verdict on these rows, so this is the original
    pre-registered rule behaving as written, not a side effect of the
    amendments; the shadow comparison confirms it. The verdict's direction
    is conservative -- it can only ever stop a promotion -- and in the
    funnel a null never reaches the battery at all (the screen and
    replication gates are upstream). Re-judging leg (i) because we saw what
    it kills is the one move the battery's docstring forbids."""

    def test_no_shape_rule_fires_on_exactly_null_data(self):
        result = battery.run(_null_rows(), dose_key="dose")
        self.assertTrue(result["ran"])
        self.assertAlmostEqual(result["report"]["baseline"]["effect"], 0.0)
        for shape_rule in ("season_split", "extreme_removal",
                          "dose_response"):
            self.assertNotIn(shape_rule, result["fatal"],
                             f"{shape_rule} claims a pattern in pure noise")

    def test_an_exact_null_is_never_endorsed(self):
        result = battery.run(_null_rows(), dose_key="dose")
        self.assertFalse(
            result["survives"],
            "an exact null came out survives=True with ran=True -- the "
            "battery endorsed nothing-at-all as unfalsified")
        for name in result["fatal"]:
            self.assertIn(name, ("team_concentration", "book_concentration"),
                          "only the concentration leg (i) may fire on a null")


class GeneralityHygieneTests(unittest.TestCase):
    """The rules must be generic machinery, not a memorial to one autopsy."""

    # M3's markers plus real sportsbook and team identifiers. If any fatal
    # rule's source names one of these, the rule is tuned to a case, not a
    # shape, and every verdict it produces is suspect.
    FORBIDDEN = ("m3", "M3", "fanduel", "FanDuel", "draftkings", "DraftKings",
                 "betmgm", "BetMGM", "caesars", "Caesars", "pinnacle",
                 "Pinnacle", "circa", "Circa", "bet365", "NYY", "BOS", "LAD",
                 "yankees", "Yankees", "dodgers", "Dodgers")

    RULES = (battery._season_split, battery._concentration,
             battery._extreme_removal, battery._dose_response,
             battery._spike_signature)

    def test_no_fatal_rule_names_a_case_a_book_or_a_team(self):
        for rule in self.RULES:
            source = inspect.getsource(rule)
            for token in self.FORBIDDEN:
                self.assertNotIn(
                    token, source,
                    f"{rule.__name__} source contains '{token}'")

    def test_the_rule_set_is_versioned_and_stably_fingerprinted(self):
        self.assertTrue(hasattr(battery, "RULES_VERSION"))
        self.assertIsInstance(battery.RULES_VERSION, str)
        first = battery.rules_fingerprint()
        second = battery.rules_fingerprint()
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{16}$")


if __name__ == "__main__":
    unittest.main()
