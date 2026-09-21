"""UFC_CARD_V1 (src/analysis/ufc_card.py): the pre-registered selector.

Each test pins one rule from docs/PREREG_UFC_CARD_V1.md. The favourite/dog
boundary rules (rule 4) are tested two ways: end-to-end through `select`
from raw multibook rows (so the real de-vig math is exercised), and
directly against `bout_candidate` with a hand-built consensus dict (so the
-200/+100..+150/0.45 boundaries themselves are pinned without depending on
finding real prices whose de-vig happens to land exactly on a boundary).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.analysis import ufc_card

NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
COMMENCE = (NOW + timedelta(hours=4)).isoformat().replace("+00:00", "Z")


def _row(book, home_price, away_price, *, event_id="bout1",
        home="Fighter A", away="Fighter B", commence=COMMENCE):
    return {
        "event_id": event_id, "market": "h2h", "commence_time": commence,
        "home_team": home, "away_team": away, "book": book,
        "home_price": home_price, "away_price": away_price,
        "observed_utc": NOW.isoformat(), "sport": "mma",
    }


def _books(n, make):
    return [make(f"book{i}") for i in range(n)]


def _consensus(**kw):
    base = {"n_books": 5, "home_team": "Fighter A", "away_team": "Fighter B",
            "commence_time": COMMENCE, "home_probability": 0.6,
            "away_probability": 0.4, "home_avg_price": -150.0,
            "away_avg_price": 130.0}
    base.update(kw)
    return base


class MinBooksRule(unittest.TestCase):
    def test_fewer_than_three_books_is_never_evaluated(self):
        rows = _books(2, lambda b: _row(b, -150, 130))
        self.assertEqual(ufc_card.select(rows, now=NOW), [])
        boards = ufc_card._upcoming_bouts(rows, now=NOW)
        self.assertIsNone(ufc_card.bout_consensus(boards["bout1"]))

    def test_exactly_three_books_is_evaluated(self):
        rows = _books(3, lambda b: _row(b, -150, 130))
        boards = ufc_card._upcoming_bouts(rows, now=NOW)
        consensus = ufc_card.bout_consensus(boards["bout1"])
        self.assertIsNotNone(consensus)
        self.assertEqual(consensus["n_books"], 3)


class FavouritePriceCapEndToEnd(unittest.TestCase):
    def test_minus_199_favourite_is_allowed(self):
        rows = _books(5, lambda b: _row(b, -199, 175))
        picks = ufc_card.select(rows, now=NOW)
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["side"], "home")
        self.assertEqual(picks[0]["label"], "FAVOURITE")

    def test_minus_200_favourite_is_refused(self):
        rows = _books(5, lambda b: _row(b, -200, 180))
        picks = ufc_card.select(rows, now=NOW)
        self.assertEqual(picks, [])

    def test_heavy_favourite_with_no_qualifying_dog_produces_no_pick(self):
        rows = _books(5, lambda b: _row(b, -400, 320))
        picks = ufc_card.select(rows, now=NOW)
        self.assertEqual(picks, [])


class FavouriteAndDogBoundaries(unittest.TestCase):
    """Direct `bout_candidate` tests -- pins the exact -200 / +100..+150 /
    0.45 boundaries in docs/PREREG_UFC_CARD_V1.md item 4."""

    def test_favourite_exactly_minus_200_is_refused(self):
        c = _consensus(home_avg_price=-200.0, away_avg_price=130.0, away_probability=0.30)
        self.assertIsNone(ufc_card.bout_candidate(c))

    def test_favourite_minus_199_qualifies(self):
        c = _consensus(home_avg_price=-199.0)
        cand = ufc_card.bout_candidate(c)
        self.assertIsNotNone(cand)
        self.assertEqual(cand["kind"], "favourite")
        self.assertEqual(cand["side"], "home")

    def test_dog_qualifies_when_favourite_disqualified_and_dog_clears_threshold(self):
        c = _consensus(home_avg_price=-250.0, away_avg_price=140.0, away_probability=0.45)
        cand = ufc_card.bout_candidate(c)
        self.assertIsNotNone(cand)
        self.assertEqual(cand["kind"], "dog")
        self.assertEqual(cand["side"], "away")

    def test_dog_just_under_threshold_is_refused(self):
        c = _consensus(home_avg_price=-250.0, away_avg_price=140.0, away_probability=0.4499)
        self.assertIsNone(ufc_card.bout_candidate(c))

    def test_dog_priced_above_150_is_refused_even_with_enough_probability(self):
        c = _consensus(home_avg_price=-250.0, away_avg_price=160.0, away_probability=0.50)
        self.assertIsNone(ufc_card.bout_candidate(c))

    def test_dog_priced_below_100_is_refused(self):
        c = _consensus(home_avg_price=-250.0, away_avg_price=90.0, away_probability=0.50)
        self.assertIsNone(ufc_card.bout_candidate(c))

    def test_favourite_qualifying_wins_the_tiebreak_over_a_qualifying_dog(self):
        # Both sides would technically pass their own rule; the favourite
        # path is checked first and is the bout's only candidate.
        c = _consensus(home_avg_price=-150.0, away_avg_price=130.0,
                       home_probability=0.6, away_probability=0.46)
        cand = ufc_card.bout_candidate(c)
        self.assertEqual(cand["kind"], "favourite")


class RankingAndCap(unittest.TestCase):
    def test_ranked_by_consensus_probability_and_capped(self):
        rows = []
        for i, price in enumerate([-110, -130, -150, -170, -190, -105]):
            rows += _books(5, lambda b, p=price, ev=f"bout{i}": _row(b, p, -p + 20, event_id=ev))
        picks = ufc_card.select(rows, now=NOW, max_picks=5)
        self.assertEqual(len(picks), 5)
        probs = [p["market_probability"] for p in picks]
        self.assertEqual(probs, sorted(probs, reverse=True))
        for i, pick in enumerate(picks, start=1):
            self.assertEqual(pick["rank"], i)

    def test_one_pick_per_bout(self):
        rows = _books(6, lambda b: _row(b, -180, 155))
        picks = ufc_card.select(rows, now=NOW)
        self.assertLessEqual(len(picks), 1)


class LockAndBoutsNotYetStarted(unittest.TestCase):
    def test_a_bout_that_already_started_is_not_evaluated(self):
        past = (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        rows = _books(5, lambda b: _row(b, -150, 130, commence=past))
        picks = ufc_card.select(rows, now=NOW)
        self.assertEqual(picks, [])

    def test_lock_lead_hours_matches_the_sport_spec(self):
        from src.sports import mma as mma_spec
        self.assertEqual(ufc_card.LOCK_LEAD_HOURS, mma_spec.MMA.lock_lead_hours)
        self.assertEqual(ufc_card.LOCK_LEAD_HOURS, 1.5)


class NoProvenEdgeLanguage(unittest.TestCase):
    def test_card_copy_never_claims_a_proven_edge(self):
        for text in (ufc_card.CARD_BASIS, ufc_card.CARD_DISCLAIMER):
            self.assertNotIn("proven edge", text.lower())
            self.assertNotIn("guaranteed", text.lower())


if __name__ == "__main__":
    unittest.main()
