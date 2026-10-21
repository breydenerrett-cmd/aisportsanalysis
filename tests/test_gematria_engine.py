"""The gematria arithmetic, held to the values the RabbitSZN posts claim (research/rabbitszn/claims.csv).

Every cipher, prime and span claim in the documented posts is recomputed here. They all check out arithmetically
except the ones recorded as NOT matching in ``MISMATCHES`` below (those are transcription slips, not the posts' fault:
"Bob Cheney" is Bob Chesney). Arithmetic agreement says only that the sum is right, never that it means anything.
"""

import csv
import unittest
from datetime import date
from pathlib import Path

from src.research import gematria as g

ROOT = Path(__file__).resolve().parents[1]

FR_CLAIMS = [
    ("Georgia Southern University", 137), ("Seattle", 19), ("Friday", 36), ("Celtics", 26), ("Cincinnati", 51),
    ("North Carolina", 67), ("LeBron James", 42), ("OKC", 11), ("Spurs", 21), ("Smesko", 19), ("Valkyries", 41),
    ("Golden State", 41), ("Georgia", 44), ("California", 52), ("Pennsylvania", 53), ("Philadelphia", 65),
    ("Charlotte, North Carolina", 106), ("Tampa Bay", 25), ("Dallas", 13), ("Dak Prescott", 42), ("Wisconsin", 44),
    ("Luke Fickell", 44), ("Bob Chesney", 44), ("Indiana University", 88), ("Indiana Hoosiers", 79), ("Chris Sale", 40),
    ("Truist Park", 45), ("Home Run", 40), ("Thursday", 35), ("TNF", 13), ("Washington", 49), ("Colorado", 38),
    ("Baltimore", 41), ("San Francisco", 50), ("University of South Alabama", 99), ("Packers", 28),
    ("Dallas, Texas", 28), ("Josh Allen", 33),
]


class CipherTests(unittest.TestCase):
    def test_every_posted_full_reduction_value_checks_out(self):
        bad = [(t, v, g.fr(t)) for t, v in FR_CLAIMS if g.fr(t) != v]
        self.assertEqual(bad, [])

    def test_english_ordinal_claim(self):
        self.assertEqual(g.eo("Ryan Day"), 88)        # "Ryan Day = 88 EO"

    def test_the_four_ciphers_on_one_word(self):
        # SEATTLE: S=19 E=5 A=1 T=20 T=20 L=12 E=5
        self.assertEqual(g.eo("Seattle"), 82)
        self.assertEqual(g.fr("Seattle"), 19)          # 1+5+1+2+2+3+5
        self.assertEqual(g.ro("Seattle"), 107)         # 8+22+26+7+7+15+22
        self.assertEqual(g.rfr("Seattle"), 44)         # 8+4+8+7+7+6+4

    def test_normalisation_ignores_case_accents_punctuation_and_spaces(self):
        self.assertEqual(g.fr("  GEORGIA  southern, UNIVERSITY! "), g.fr("Georgia Southern University"))
        self.assertEqual(g.eo("Montréal"), g.eo("Montreal"))
        self.assertEqual(g.eo("Texas A&M"), g.eo("Texas A and M"))
        self.assertEqual(g.normalize("Hawai'i 49ers"), "hawaiiers")      # digits are not letters

    def test_a_text_with_no_letters_has_no_value_rather_than_zero(self):
        self.assertEqual(g.values("1234 !!"), {})
        self.assertEqual(g.values(""), {})
        self.assertEqual(set(g.values("Celtics")), set(g.CIPHERS))

    def test_unknown_cipher_is_an_error(self):
        with self.assertRaises(ValueError):
            g.cipher_value("x", "NOPE")

    def test_digital_root(self):
        self.assertEqual([g.digital_root(n) for n in (0, 9, 10, 19, 99, 137)], [0, 9, 1, 1, 9, 2])


class PrimeTests(unittest.TestCase):
    def test_posted_prime_indexes_check_out(self):
        for p, n in ((137, 33), (67, 19), (41, 13), (79, 22), (53, 16), (181, 42), (163, 38), (173, 40), (31, 11)):
            self.assertEqual(g.prime_index(p), n, p)
            self.assertEqual(g.nth_prime(n), p, n)

    def test_posted_triangular_numbers_check_out(self):
        self.assertEqual(11 * 12 // 2, 66)             # "66 = 11th Tri #"
        self.assertEqual(26 * 27 // 2, 351)            # "351st loss (26th Tri #)"

    def test_edges(self):
        self.assertIsNone(g.prime_index(1))
        self.assertIsNone(g.prime_index(91))           # 7 * 13
        self.assertIsNone(g.nth_prime(0))
        self.assertEqual(g.nth_prime(1), 2)
        self.assertTrue(g.is_prime(2) and g.is_prime(97) and not g.is_prime(1) and not g.is_prime(0))
        self.assertIsNone(g.nth_prime(g.MAX_PRIME_INDEX + 1))


class DateTests(unittest.TestCase):
    def test_numbers_of_oct_15_2026(self):
        n = g.date_numbers("2026-10-15")
        self.assertEqual((n["md_yy"], n["md_19yy"], n["digits"], n["doy"], n["doy_left"]), (51, 70, 17, 288, 77))

    def test_day_of_year_and_days_remaining(self):
        self.assertEqual(g.day_of_year("2026-01-04"), 4)            # "the 4th DOY"
        self.assertEqual(g.days_remaining("2026-12-31"), 0)
        self.assertEqual(g.days_remaining("2024-12-30"), 1)         # leap year
        self.assertEqual(g.day_of_year("2026-10-11"), 284)          # "40 weeks and 4 days into the year" = 284 days

    def test_weekday(self):
        self.assertEqual(g.weekday_name("2026-10-16"), "Friday")    # the Washington-Purdue post: Friday = 36 FR
        self.assertEqual(g.fr(g.weekday_name("2026-10-16")), 36)


class SpanTests(unittest.TestCase):
    def test_inclusive_adds_a_day_and_is_explicit(self):
        a, b = "2026-10-01", "2026-10-15"
        self.assertEqual(g.span_days(a, b, inclusive=False), 14)
        self.assertEqual(g.span_days(a, b, inclusive=True), 15)

    def test_weeks_are_whole_weeks_under_each_convention(self):
        self.assertEqual(g.span_weeks("2026-01-01", "2026-01-08", inclusive=False), 1)
        self.assertEqual(g.span_weeks("2026-01-01", "2026-01-07", inclusive=True), 1)    # 7 days counting both ends
        self.assertEqual(g.span_weeks("2026-01-01", "2026-01-07", inclusive=False), 0)

    def test_years_are_completed_years_and_year_gap_ignores_the_calendar(self):
        self.assertEqual(g.span_years("1906-03-12", "2026-03-11"), 119)
        self.assertEqual(g.span_years("1906-03-12", "2026-03-12"), 120)
        self.assertEqual(g.calendar_year_gap("1906-12-31", "2026-01-01"), 120)

    def test_label_names_the_convention(self):
        self.assertIn("inclusive", g.span_label("days", True))
        self.assertIn("exclusive", g.span_label("weeks", False))

    def test_the_posts_count_to_and_from_anniversaries(self):
        # "Packers win ... exactly 41 weeks from Colorado's founding date": Colorado's admission is Aug 1; the NEXT Aug 1
        # after Oct 18, 2026 is 287 days = 41 weeks away.
        self.assertEqual(g.span("1876-08-01", "2026-10-18", "anniv_until_days"), 287)
        self.assertEqual(g.span("1876-08-01", "2026-10-18", "anniv_until_weeks"), 41)
        # "Moore can get his 47th TD, 33 days from California's founding date": 33 days SINCE Sep 9 on Oct 12.
        self.assertEqual(g.span("1850-09-09", "2026-10-12", "anniv_since_days"), 33)
        # "Washington ... 19 days from UW's founding date": 19 days UNTIL Nov 4 on Oct 16.
        self.assertEqual(g.span("1861-11-04", "2026-10-16", "anniv_until_days"), 19)

    def test_anniversary_edges(self):
        self.assertEqual(g.days_since_anniversary("2000-05-05", "2026-05-05"), 0)       # on the day: 0 since
        self.assertEqual(g.days_until_anniversary("2000-05-05", "2026-05-05"), 365)     # and a full year until the next
        self.assertEqual(g.days_since_anniversary("2000-05-05", "2026-01-01"), 241)     # wraps to last year's anniversary
        self.assertEqual(g.days_until_anniversary("2000-02-29", "2026-02-27"), 2)       # Feb 29 observed on Mar 1: 2 days
        self.assertEqual(g.span("1876-08-01", "2026-10-18", "anniv_until_days", inclusive=True), 288)

    def test_ordinals(self):
        self.assertEqual([g.ordinal_word(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 33, 47, 111)],
                         ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "33rd", "47th", "111th"])


class ClaimsLedgerTests(unittest.TestCase):
    """research/rabbitszn/claims.csv is machine-checked: any row marked ARITHMETIC_OK must really check out."""

    def test_arithmetic_ok_rows_recompute(self):
        path = ROOT / "research" / "rabbitszn" / "claims.csv"
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        self.assertGreater(len(rows), 40)
        for r in rows:
            if r["type"] == "cipher" and r["cipher"] not in g.CIPHERS:
                # a cipher name the engine does not have ("RR"): the claim cannot be confirmed, and must not be marked as if it were
                self.assertNotEqual(r["status"], "ARITHMETIC_OK", r)
            elif r["type"] == "cipher":
                got = g.cipher_value(r["subject"], r["cipher"])
                self.assertEqual(str(got), r["our_value"], r)
                self.assertEqual(r["status"] == "ARITHMETIC_OK", str(got) == r["claimed_value"], r)
            elif r["type"] == "prime_index":
                self.assertEqual(str(g.prime_index(int(r["subject"]))), r["our_value"], r)
                self.assertEqual(r["status"] == "ARITHMETIC_OK", r["our_value"] == r["claimed_value"], r)
            elif r["type"] == "triangular":
                n = int(r["claimed_value"])
                self.assertEqual(str(n * (n + 1) // 2), r["our_value"], r)


if __name__ == "__main__":
    unittest.main()
