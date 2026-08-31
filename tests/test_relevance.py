"""Tests for src/analysis/relevance.py -- pre-event relevance scoring.

Four properties matter here, and they are exactly the ones a descriptive
score can quietly lose:

  * POINT-IN-TIME HONESTY. A pitch dated on or after the cutoff must not move
    a score by one BYTE, and the identical payload dated before the cutoff
    must move it -- otherwise the silence proves nothing. Same injection
    discipline as tests/test_matrix_v5_features.py.
  * UNKNOWN, NOT LOW. A player with no record before the cutoff is
    uncharacterized, and UNKNOWN carries no rank so nothing can average it in
    as a zero.
  * MONOTONICITY. More established workload never scores lower.
  * SHAPE. The dicts rosterwatch.events() actually emits are scored verbatim,
    with no adapter in between.

The fixture is a tiny gzipped store in statcast_pitches' exact on-disk shape,
read through the real accumulation primitive -- nothing is stubbed.

Pitchers, hand-checkable:
  700  6 appearances x 90 pitches  -> 6 starting appearances, 90.0 each: HIGH
  710  5 appearances x 85 pitches  -> exactly at both floors: HIGH
  720  2 appearances x 45 pitches  -> 2 starting appearances, 90 pitches: MEDIUM
  730  1 appearance  x 15 pitches  -> no starting appearance, 15 pitches: LOW
  750  20 appearances x 16 pitches -> no starting appearance, 320 pitches:
       MEDIUM by total volume alone (a bullpen arm with a real record)
  740  nothing at all              -> UNKNOWN
Batters:
  9001 320 PA over 80 games -> HIGH      9002 120 PA over 60 games -> MEDIUM
  9003 20 PA over 20 games  -> LOW       9004 nothing -> UNKNOWN
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.analysis import relevance
from src.pipeline import rosterwatch

CUTOFF = "2023-05-01"
BASE_WINDOW = "2023-04-01..2023-04-04"
PRE_WINDOW = "2023-04-20..2023-04-23"    # still before the cutoff
POST_WINDOW = "2023-05-05..2023-05-08"   # after it


def _row(day, game_pk, pitcher, batter, denom="0"):
    """One stored pitch in statcast_pitches.KEEP's shape."""
    return {"game_date": day, "game_pk": game_pk, "pitcher": pitcher,
            "batter": batter, "stand": "R", "p_throws": "R",
            "pitch_type": "FF", "release_speed": "93.0",
            "description": "hit_into_play", "events": "field_out",
            "woba_value": "0.0", "woba_denom": denom, "at_bat_number": "1",
            "pitch_number": "1", "inning": "1", "home_team": "SEA",
            "away_team": "CLE", "bb_type": "ground_ball"}


def _appearances(pitcher, games, pitches, first_pk, day="2023-04-01"):
    """`games` appearances of `pitches` pitches each, one game_pk apiece.

    Batter 9500 is filler with a zero wOBA denominator, so these rows give
    the pitcher a workload without quietly making the filler a hitter with
    plate appearances.
    """
    rows = []
    for index in range(games):
        pk = str(first_pk + index)
        rows += [_row(day, pk, pitcher, "9500") for _ in range(pitches)]
    return rows


def _plate_appearances(batter, games, per_game, first_pk, day="2023-04-02"):
    rows = []
    for index in range(games):
        pk = str(first_pk + index)
        rows += [_row(day, pk, "999", batter, denom="1")
                 for _ in range(per_game)]
    return rows


def _fixture_rows() -> list:
    rows = []
    rows += _appearances("700", 6, 90, 1000)
    rows += _appearances("710", 5, 85, 1100)
    rows += _appearances("720", 2, 45, 1200)
    rows += _appearances("730", 1, 15, 1300)
    rows += _appearances("750", 20, 16, 1400)
    rows += _plate_appearances("9001", 80, 4, 2000)
    rows += _plate_appearances("9002", 60, 2, 2100)
    rows += _plate_appearances("9003", 20, 1, 2200)
    return rows


def _write_store(root: Path, windows: dict) -> Path:
    """A store in the on-disk shape statcast_pitches.iter_rows expects."""
    store = root / "statcast"
    store.mkdir(parents=True, exist_ok=True)
    manifest = {"windows": {}}
    for key, rows in windows.items():
        name = f"pitches_{key}.jsonl.gz"
        with gzip.open(store / name, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        manifest["windows"][key] = {"rows": len(rows), "file": name}
    (store / "manifest.json").write_text(json.dumps(manifest),
                                         encoding="utf-8")
    return store


class StoreCase(unittest.TestCase):
    """One shared fixture store and index for the scoring tests."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.store = _write_store(Path(cls._tmp.name),
                                 {BASE_WINDOW: _fixture_rows()})
        cls.index = relevance.build_index(CUTOFF, store=cls.store)


# ---------------------------------------------------------------------------
# The index itself
# ---------------------------------------------------------------------------

class IndexTest(StoreCase):

    def test_pitcher_workload_arithmetic(self):
        facts = self.index["pitchers"]["700"]
        self.assertEqual(facts["pitches"], 540)
        self.assertEqual(facts["appearances"], 6)
        self.assertEqual(facts["starting_appearances"], 6)
        self.assertEqual(facts["pitches_per_start"], 90.0)

    def test_short_outings_are_not_starting_appearances(self):
        facts = self.index["pitchers"]["750"]
        self.assertEqual(facts["pitches"], 320)
        self.assertEqual(facts["appearances"], 20)
        # 16 pitches an outing is under STARTING_APPEARANCE_PITCHES, so the
        # per-start mean has no appearances to average and stays None.
        self.assertEqual(facts["starting_appearances"], 0)
        self.assertIsNone(facts["pitches_per_start"])

    def test_batter_volume_arithmetic(self):
        facts = self.index["batters"]["9001"]
        self.assertEqual(facts["plate_appearances"], 320)
        self.assertEqual(facts["games"], 80)

    def test_zero_denominator_rows_are_not_plate_appearances(self):
        # Filler batter 9500 was on the receiving end of 1390 pitches with a
        # zero wOBA denominator; none of them is a plate appearance.
        self.assertEqual(self.index["batters"]["9500"]["plate_appearances"], 0)

    def test_absent_player_is_absent(self):
        self.assertNotIn("740", self.index["pitchers"])
        self.assertNotIn("9004", self.index["batters"])


# ---------------------------------------------------------------------------
# The scale
# ---------------------------------------------------------------------------

class TierScaleTest(unittest.TestCase):

    def test_unknown_has_no_rank(self):
        self.assertIsNone(relevance.tier_rank(relevance.UNKNOWN))

    def test_scale_is_ordered(self):
        self.assertLess(relevance.tier_rank(relevance.LOW),
                        relevance.tier_rank(relevance.MEDIUM))
        self.assertLess(relevance.tier_rank(relevance.MEDIUM),
                        relevance.tier_rank(relevance.HIGH))

    def test_pitcher_tier_is_monotone_in_workload(self):
        # Constructed ladder: each rung is at least as established as the one
        # below it, so its tier may never rank lower.
        ladder = [
            {"pitches": 0, "appearances": 0, "starting_appearances": 0,
             "pitches_per_start": None, "batters_faced": 0},
            {"pitches": 15, "appearances": 1, "starting_appearances": 0,
             "pitches_per_start": None, "batters_faced": 4},
            {"pitches": 90, "appearances": 2, "starting_appearances": 2,
             "pitches_per_start": 45.0, "batters_faced": 24},
            {"pitches": 425, "appearances": 5, "starting_appearances": 5,
             "pitches_per_start": 85.0, "batters_faced": 110},
            {"pitches": 900, "appearances": 10, "starting_appearances": 10,
             "pitches_per_start": 90.0, "batters_faced": 240},
        ]
        ranks = [relevance.tier_rank(relevance.pitcher_tier(f))
                 for f in ladder]
        self.assertIsNone(ranks[0])  # no record: UNKNOWN, off the scale
        self.assertEqual(ranks[1:], sorted(ranks[1:]))
        self.assertEqual(relevance.pitcher_tier(ladder[-1]), relevance.HIGH)

    def test_pitcher_floors_are_inclusive(self):
        at_floor = {"pitches": 425, "appearances": 5,
                    "starting_appearances": relevance.ESTABLISHED_STARTS,
                    "pitches_per_start": relevance.DEEP_START_PITCHES,
                    "batters_faced": 110}
        self.assertEqual(relevance.pitcher_tier(at_floor), relevance.HIGH)
        one_short = dict(at_floor,
                         starting_appearances=relevance.ESTABLISHED_STARTS - 1)
        self.assertEqual(relevance.pitcher_tier(one_short), relevance.MEDIUM)
        shallow = dict(at_floor,
                       pitches_per_start=relevance.DEEP_START_PITCHES - 0.1)
        self.assertEqual(relevance.pitcher_tier(shallow), relevance.MEDIUM)

    def test_batter_tier_is_monotone_in_plate_appearances(self):
        ladder = [0, 20, 99, 100, 299, 300, 600]
        ranks = [relevance.tier_rank(
            relevance.batter_tier({"plate_appearances": pa,
                                   "games": 1 if pa else 0}))
            for pa in ladder]
        self.assertIsNone(ranks[0])
        self.assertEqual(ranks[1:], sorted(ranks[1:]))
        self.assertEqual(ranks[3], relevance.tier_rank(relevance.MEDIUM))
        self.assertEqual(ranks[5], relevance.tier_rank(relevance.HIGH))


# ---------------------------------------------------------------------------
# starter_scratch
# ---------------------------------------------------------------------------

def _starter_scratch(from_id, to_id):
    """The shape rosterwatch._probable_events emits."""
    return {"class": rosterwatch.STARTER_SCRATCH, "game_pk": 1,
            "interval": ("2023-05-01T17:00:00+00:00",
                         "2023-05-01T17:15:00+00:00"),
            "inadmissible": False,
            "detail": {"side": "home", "from": from_id, "to": to_id}}


class StarterScratchTest(StoreCase):

    def score(self, from_id, to_id):
        return relevance.score_event(_starter_scratch(from_id, to_id), CUTOFF,
                                     index=self.index)

    def test_established_starter_scores_high(self):
        score = self.score(700, 730)
        self.assertEqual(score["tier"], relevance.HIGH)
        self.assertEqual(score["rank"], 2)
        self.assertIsNone(score["unknown_reason"])

    def test_basis_carries_both_arms_with_their_samples(self):
        basis = self.score(700, 730)["basis"]
        self.assertEqual([b["part"] for b in basis],
                         ["scratched", "replacement"])
        self.assertEqual(basis[0]["pitches"], 540)
        self.assertEqual(basis[0]["starting_appearances"], 6)
        self.assertEqual(basis[1]["pitches"], 15)

    def test_like_for_like_swap_steps_down(self):
        # Both arms clear the established-starter floor, so the swap is
        # nearer like-for-like than a star for an unknown.
        score = self.score(700, 710)
        self.assertEqual(score["tier"], relevance.MEDIUM)
        self.assertTrue(any("like-for-like" in r for r in score["reasons"]))

    def test_replacement_never_raises_the_tier(self):
        # A spot starter replaced by nobody-in-particular stays MEDIUM.
        self.assertEqual(self.score(720, 730)["tier"], relevance.MEDIUM)
        # And replaced by an established arm, still MEDIUM -- the rule only
        # ever steps down.
        self.assertEqual(self.score(720, 700)["tier"], relevance.MEDIUM)

    def test_cameo_arm_scores_low(self):
        self.assertEqual(self.score(730, 700)["tier"], relevance.LOW)

    def test_unseen_pitcher_is_unknown_not_low(self):
        score = self.score(740, 700)
        self.assertEqual(score["tier"], relevance.UNKNOWN)
        self.assertIsNone(score["rank"])
        self.assertIn("unknown, not low", score["unknown_reason"])

    def test_missing_scratched_id_is_unknown(self):
        score = relevance.score_event(
            {"class": rosterwatch.STARTER_SCRATCH,
             "detail": {"side": "home", "from": None, "to": 700}},
            CUTOFF, index=self.index)
        self.assertEqual(score["tier"], relevance.UNKNOWN)


# ---------------------------------------------------------------------------
# hitter_scratch
# ---------------------------------------------------------------------------

def _hitter_scratch(removed):
    """The shape rosterwatch._lineup_events emits for a scratch."""
    return {"class": rosterwatch.HITTER_SCRATCH, "game_pk": 1,
            "interval": ("2023-05-01T17:00:00+00:00",
                         "2023-05-01T17:15:00+00:00"),
            "inadmissible": False,
            "detail": {"side": "away", "removed": removed}}


class HitterScratchTest(StoreCase):

    def score(self, removed, lineup=None):
        return relevance.score_event(_hitter_scratch(removed), CUTOFF,
                                     index=self.index, lineup=lineup)

    def test_regular_scores_high(self):
        score = self.score([9001])
        self.assertEqual(score["tier"], relevance.HIGH)
        self.assertEqual(score["basis"][0]["plate_appearances"], 320)
        self.assertEqual(score["basis"][0]["games"], 80)

    def test_part_timer_scores_medium(self):
        self.assertEqual(self.score([9002])["tier"], relevance.MEDIUM)

    def test_top_of_the_order_promotes(self):
        lineup = [9002, 9003, 9500, 9501, 9502, 9503, 9504, 9505, 9506]
        score = self.score([9002], lineup=lineup)
        self.assertEqual(score["basis"][0]["lineup_slot"], 1)
        self.assertEqual(score["tier"], relevance.HIGH)

    def test_bottom_of_the_order_demotes(self):
        lineup = [9500, 9501, 9502, 9503, 9504, 9505, 9506, 9002, 9507]
        score = self.score([9002], lineup=lineup)
        self.assertEqual(score["basis"][0]["lineup_slot"], 8)
        self.assertEqual(score["tier"], relevance.LOW)

    def test_middle_slot_adjusts_nothing(self):
        lineup = [9500, 9501, 9502, 9503, 9002, 9504, 9505, 9506, 9507]
        self.assertEqual(self.score([9002], lineup=lineup)["tier"],
                         relevance.MEDIUM)

    def test_unsupplied_lineup_leaves_the_slot_absent(self):
        score = self.score([9002])
        self.assertIsNone(score["basis"][0]["lineup_slot"])
        self.assertEqual(score["tier"], relevance.MEDIUM)

    def test_biggest_loss_sets_the_tier(self):
        score = self.score([9003, 9001])
        self.assertEqual(score["tier"], relevance.HIGH)
        self.assertEqual(len(score["basis"]), 2)

    def test_unknown_hitter_does_not_drag_a_known_one_down(self):
        score = self.score([9004, 9001])
        self.assertEqual(score["tier"], relevance.HIGH)
        self.assertEqual(score["basis"][0]["tier"], relevance.UNKNOWN)

    def test_all_unseen_hitters_score_unknown(self):
        score = self.score([9004])
        self.assertEqual(score["tier"], relevance.UNKNOWN)
        self.assertIsNone(score["rank"])
        self.assertIn("unknown, not low", score["unknown_reason"])

    def test_promotion_never_lifts_unknown(self):
        lineup = [9004, 9001, 9002, 9003, 9500, 9501, 9502, 9503, 9504]
        score = self.score([9004], lineup=lineup)
        self.assertEqual(score["tier"], relevance.UNKNOWN)


# ---------------------------------------------------------------------------
# lineup_posted and transactions
# ---------------------------------------------------------------------------

class LineupPostedTest(StoreCase):

    def test_class_constant_with_its_reason(self):
        event = {"class": rosterwatch.LINEUP_POSTED, "game_pk": 1,
                 "interval": (None, "2023-05-01T17:15:00+00:00"),
                 "inadmissible": True,
                 "detail": {"side": "away", "note": "first sighting"}}
        score = relevance.score_event(event, CUTOFF, index=self.index)
        self.assertEqual(score["tier"], relevance.MEDIUM)
        self.assertEqual(score["basis"], [])
        self.assertIn("class constant", score["reasons"][0])


def _transaction_event(transaction_id=55):
    return {"class": rosterwatch.TRANSACTION_SEEN,
            "transaction_id": transaction_id,
            "interval": ("2023-05-01T17:00:00+00:00",
                         "2023-05-01T17:15:00+00:00"),
            "inadmissible": False, "detail": None}


class TransactionTest(StoreCase):

    def score(self, transaction):
        return relevance.score_event(_transaction_event(), CUTOFF,
                                     index=self.index, transaction=transaction)

    def test_id_alone_is_unknown(self):
        score = self.score(None)
        self.assertEqual(score["tier"], relevance.UNKNOWN)
        self.assertIn("keeps only the id", score["unknown_reason"])

    def test_il_placement_of_a_regular_scores_high(self):
        score = self.score({"category": "il_placement", "player_id": 9001})
        self.assertEqual(score["tier"], relevance.HIGH)
        self.assertEqual(score["basis"][0]["role"], "batter")

    def test_il_placement_of_a_workhorse_starter_scores_high(self):
        score = self.score({"category": "il_placement", "player_id": 700})
        self.assertEqual(score["tier"], relevance.HIGH)
        self.assertEqual(score["basis"][0]["role"], "pitcher")

    def test_depth_move_is_capped_below_the_top_tier(self):
        score = self.score({"category": "recalled", "player_id": 700})
        self.assertEqual(score["tier"], relevance.MEDIUM)
        self.assertTrue(any("bottom-of-roster" in r for r in score["reasons"]))

    def test_non_availability_category_scores_low(self):
        score = self.score({"category": "rehab", "player_id": 9001})
        self.assertEqual(score["tier"], relevance.LOW)

    def test_september_callup_is_unknown_not_low(self):
        score = self.score({"category": "recalled", "player_id": 740})
        self.assertEqual(score["tier"], relevance.UNKNOWN)
        self.assertIsNone(score["rank"])
        self.assertIn("unknown, not low", score["unknown_reason"])

    def test_transaction_without_a_player_is_unknown(self):
        self.assertEqual(self.score({"category": "traded"})["tier"],
                         relevance.UNKNOWN)


class UnknownClassTest(StoreCase):

    def test_unscorable_class_raises(self):
        with self.assertRaises(relevance.RelevanceError):
            relevance.score_event({"class": "weather_roof"}, CUTOFF,
                                  index=self.index)


# ---------------------------------------------------------------------------
# Event shapes straight out of rosterwatch.events()
# ---------------------------------------------------------------------------

class RosterWatchShapeTest(StoreCase):
    """The real capture path: poll a faked world, derive events, score them
    verbatim. No adapter, no hand-built dict."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._watch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._watch.cleanup)
        watch_dir = Path(cls._watch.name)
        clock = {"now": datetime(2023, 5, 1, 15, 0, tzinfo=timezone.utc)}

        def tick(minutes):
            clock["now"] = clock["now"].replace(
                minute=clock["now"].minute + minutes)

        def poll(probables, lineups, transactions):
            rosterwatch.poll(
                game_date="2023-05-01", watch_dir=watch_dir,
                clock=lambda: clock["now"],
                fetch_probables=lambda d, timeout=20: probables,
                fetch_lineups=lambda d, timeout=20: lineups,
                fetch_transactions=lambda d, timeout=20: transactions)

        def slots(ids):
            return [{"order": i, "person_id": pid, "name": f"P{pid}",
                     "position": "1B"} for i, pid in enumerate(ids, 1)]

        listed = [{"game_pk": 1, "away_probable_id": 700,
                   "home_probable_id": 720}]
        scratched = [{"game_pk": 1, "away_probable_id": 710,
                      "home_probable_id": 720}]
        nine = [9001, 9002, 9003, 9500, 9501, 9502, 9503, 9504, 9505]
        without_9001 = [9506] + nine[1:]

        poll(listed, {}, [{"transaction_id": 55}])
        tick(15)
        poll(listed, {1: {"away": slots(nine), "home": slots(nine)}}, [])
        tick(15)
        poll(scratched, {1: {"away": slots(without_9001),
                             "home": slots(nine)}}, [])
        cls.events = rosterwatch.events(store_dir=watch_dir)
        cls.scores = relevance.score_events(
            cls.events, CUTOFF, index=cls.index,
            lineups_by_game={1: {"away": nine, "home": nine}},
            transactions={55: {"category": "il_placement",
                               "player_id": 9001}})

    def test_every_derived_event_is_scored(self):
        self.assertEqual(len(self.scores), len(self.events))
        classes = {s["class"] for s in self.scores}
        self.assertIn(rosterwatch.STARTER_SCRATCH, classes)
        self.assertIn(rosterwatch.HITTER_SCRATCH, classes)
        self.assertIn(rosterwatch.LINEUP_POSTED, classes)
        self.assertIn(rosterwatch.TRANSACTION_SEEN, classes)

    def test_scores_carry_the_event_they_describe(self):
        for score, event in zip(self.scores, self.events):
            self.assertIs(score["event"], event)
            self.assertIn("not_an_edge", score)

    def test_scratched_workhorse_reads_high_from_the_real_event(self):
        scratch = [s for s in self.scores
                   if s["class"] == rosterwatch.STARTER_SCRATCH][0]
        # 700 (six 90-pitch appearances) replaced by 710 -- both established,
        # so the like-for-like rule steps the HIGH down one.
        self.assertEqual(scratch["tier"], relevance.MEDIUM)
        self.assertEqual(scratch["basis"][0]["player_id"], "700")

    def test_hitter_slot_comes_from_the_supplied_prior_lineup(self):
        scratch = [s for s in self.scores
                   if s["class"] == rosterwatch.HITTER_SCRATCH][0]
        self.assertEqual(scratch["basis"][0]["player_id"], "9001")
        self.assertEqual(scratch["basis"][0]["lineup_slot"], 1)
        self.assertEqual(scratch["tier"], relevance.HIGH)

    def test_what_changed_reads_as_a_sentence(self):
        sentences = [relevance.what_changed(s) for s in self.scores]
        self.assertTrue(all(s.endswith(".") for s in sentences))
        self.assertTrue(any("Listed starter changed" in s for s in sentences))
        self.assertTrue(any("relevance HIGH" in s for s in sentences))

    def test_what_changed_says_unknown_out_loud(self):
        score = relevance.score_event(_starter_scratch(740, 700), CUTOFF,
                                      index=self.index)
        sentence = relevance.what_changed(score)
        self.assertIn("relevance UNKNOWN", sentence)
        self.assertIn("no pitches", sentence)


# ---------------------------------------------------------------------------
# Point-in-time honesty, at byte level
# ---------------------------------------------------------------------------

class PointInTimeTest(unittest.TestCase):
    """A payload dated after the cutoff must not move a score by one byte,
    and the identical payload dated before it MUST -- otherwise the silence
    means "ignored", not "refused"."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.root = Path(cls._tmp.name)
        cls.clean = cls._score()

    @classmethod
    def _payload(cls, day):
        """Enough workload to turn pitcher 740 from UNKNOWN into HIGH and
        hitter 9004 from UNKNOWN into HIGH -- the largest possible swing."""
        return (_appearances("740", 6, 90, 5000, day=day)
                + _plate_appearances("9004", 80, 4, 5100, day=day))

    @classmethod
    def _score(cls, extra=None, name="base"):
        windows = {BASE_WINDOW: _fixture_rows()}
        windows.update(extra or {})
        store = _write_store(cls.root / name, windows)
        index = relevance.build_index(CUTOFF, store=store)
        scores = [relevance.score_event(_starter_scratch(740, 700), CUTOFF,
                                        index=index),
                  relevance.score_event(_hitter_scratch([9004]), CUTOFF,
                                        index=index)]
        return json.dumps(scores, sort_keys=True)

    def test_clean_score_is_unknown(self):
        scores = json.loads(self.clean)
        self.assertEqual([s["tier"] for s in scores],
                         [relevance.UNKNOWN, relevance.UNKNOWN])

    def test_pitches_after_the_cutoff_cannot_move_the_score(self):
        tampered = self._score({POST_WINDOW: self._payload("2023-05-05")},
                               name="post")
        self.assertEqual(tampered, self.clean)

    def test_pitches_on_the_cutoff_day_cannot_move_the_score(self):
        tampered = self._score(
            {"2023-05-01..2023-05-04": self._payload("2023-05-01")},
            name="cutoff_day")
        self.assertEqual(tampered, self.clean)

    def test_a_datetime_cutoff_still_excludes_its_own_day(self):
        # Dossier information_times are datetimes; str(datetime) sorts after
        # the bare date, which would silently admit the day's own pitches.
        store = _write_store(
            self.root / "dt",
            {BASE_WINDOW: _fixture_rows(),
             "2023-05-01..2023-05-04": self._payload("2023-05-01")})
        index = relevance.build_index(datetime(2023, 5, 1, 23, 59),
                                      store=store)
        score = relevance.score_event(_starter_scratch(740, 700),
                                      "2023-05-01", index=index)
        self.assertEqual(score["tier"], relevance.UNKNOWN)

    def test_the_same_payload_before_the_cutoff_does_move_the_score(self):
        tampered = self._score({PRE_WINDOW: self._payload("2023-04-20")},
                               name="pre")
        self.assertNotEqual(tampered, self.clean)
        scores = json.loads(tampered)
        self.assertEqual([s["tier"] for s in scores],
                         [relevance.MEDIUM, relevance.HIGH])
        # MEDIUM, not HIGH: 740 now clears the established-starter floor and
        # so does his replacement 700, so the like-for-like rule applies --
        # which is itself proof the injected rows were read.
        self.assertEqual(scores[0]["basis"][0]["pitches"], 540)


if __name__ == "__main__":
    unittest.main()
