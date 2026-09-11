"""A pick locks at its OWN first pitch, not at the slate's earliest.

WHAT THIS REPLACED
------------------
`publish` was idempotent per DATE: the first publish won, every later run was
a no-op. Combined with the freeze gate opening four hours before the day's
EARLIEST game, the whole card was fixed once, in the morning, to protect a
matinee. A 7:40pm pick was locked at 8:15am. A scratch at 6pm could not touch
it, and what went on the record was a bet made eleven hours early on
information nobody would bet on.

The owner, 2026-09-11: "The last run scheduled or finished before the game
first pitch should be recorded, not the preview or early bets. Even if
they're rock solid and we choose to put all our eggs on a heavy no brainer,
it could change within the time frame to first pitch."

THE PROPERTY, IN TWO HALVES, AND BOTH MATTER
---------------------------------------------
A record that can be edited after the game is worthless. A record that
freezes eleven hours early records the wrong bet. So:

  LIBERTY  a pick whose game is still far out may be replaced by a better
           read, as many times as the day allows.
  LOCK     a pick within the lead of its own first pitch is final, and
           nothing after it -- not a later run, not a dropped pick, not a
           rewritten slate -- may change it.

Every test here is one or the other.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.appstate import card_ledger

NOON = datetime(2026, 9, 11, 16, 15, tzinfo=timezone.utc)      # 12:15pm ET
NIGHT = datetime(2026, 9, 11, 23, 40, tzinfo=timezone.utc)     # 7:40pm ET


def _pick(rank, game_pk, first_pitch, bet, price=-110):
    return {
        "rank": rank, "game_pk": game_pk, "bet": bet, "label": "LEAN",
        "market": "moneyline", "line": None, "side": "home", "price": price,
        "book": "somebook", "books": 8, "team_name": "Home", "away_team": "AAA",
        "home_team": "HHH", "opponent_name": "Away",
        "first_pitch_utc": first_pitch.isoformat(),
    }


def _card(picks, date="2026-09-11"):
    return {"date": date, "picks": picks, "filled": len(picks),
            "rule": "r", "basis": "b", "disclaimer": "d", "games_on_slate": 5}


class AnEveningPickKeepsImproving(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def _publish(self, picks, at):
        return card_ledger.publish(_card(picks), now=at.isoformat(),
                                   path=self.path)

    def test_the_scenario_the_owner_described(self):
        """THE ONE THAT MATTERS, end to end.

        Morning run takes both games. The matinee locks. At 6pm a scratch
        changes the evening read -- and that change must land, while the
        matinee stays exactly as it was written.
        """
        morning = NOON - timedelta(hours=4)          # 8:15am ET, matinee locks
        self._publish([_pick(1, "111", NOON, "Take Braves at -110"),
                       _pick(2, "222", NIGHT, "Take Yankees at -150")], morning)

        evening = NIGHT - timedelta(hours=5)         # 6:40pm ET, night still open
        self._publish([_pick(1, "111", NOON, "REWRITTEN MATINEE", price=-999),
                       _pick(2, "222", NIGHT, "Take Dodgers at -120",
                             price=-120)], evening)

        final = {str(p["game_pk"]): p
                 for p in card_ledger.published_row("2026-09-11",
                                                    path=self.path)["picks"]}
        self.assertEqual(final["111"]["bet"], "Take Braves at -110",
                         "the locked matinee was rewritten after its window")
        self.assertEqual(final["111"]["price"], -110)
        self.assertTrue(final["111"]["locked"])
        self.assertEqual(final["222"]["bet"], "Take Dodgers at -120",
                         "the evening pick did not take the later read")
        self.assertFalse(final["222"]["locked"])

    def test_the_evening_pick_locks_when_its_own_window_opens(self):
        morning = NOON - timedelta(hours=4)
        self._publish([_pick(2, "222", NIGHT, "Take Yankees at -150")], morning)
        late = NIGHT - timedelta(hours=3)            # inside its own lead
        self._publish([_pick(2, "222", NIGHT, "Take Yankees at -150")], late)
        row = card_ledger.published_row("2026-09-11", path=self.path)
        self.assertTrue(row["picks"][0]["locked"])
        self.assertIsNotNone(row["picks"][0]["locked_at"])

    def test_a_pick_locks_as_last_published_not_as_freshly_read(self):
        """When the window closes, what locks is the bet the READER SAW at
        the price they saw. A fresh read taken at lock time would record a
        bet nobody was shown."""
        early = NIGHT - timedelta(hours=9)
        # Price passed explicitly so the sentence and the field agree -- the
        # first version of this test let `price` default to -110 while the
        # bet text said -150, then asserted -150 and failed against correct
        # code. A fixture that contradicts itself is a test about nothing.
        self._publish([_pick(2, "222", NIGHT, "Take Yankees at -150",
                             price=-150)], early)
        at_lock = NIGHT - timedelta(hours=3)
        self._publish([_pick(2, "222", NIGHT, "DIFFERENT READ", price=+200)],
                      at_lock)
        row = card_ledger.published_row("2026-09-11", path=self.path)
        self.assertEqual(row["picks"][0]["bet"], "Take Yankees at -150")
        self.assertEqual(row["picks"][0]["price"], -150)

    def test_a_locked_pick_survives_being_dropped_from_a_later_card(self):
        """Dropping it would erase a bet of record -- the one edit that must
        be impossible."""
        morning = NOON - timedelta(hours=4)
        self._publish([_pick(1, "111", NOON, "Take Braves at -110"),
                       _pick(2, "222", NIGHT, "Take Yankees at -150")], morning)
        later = NIGHT - timedelta(hours=6)
        self._publish([_pick(2, "222", NIGHT, "Take Yankees at -150")], later)
        games = {str(p["game_pk"]) for p in
                 card_ledger.published_row("2026-09-11",
                                           path=self.path)["picks"]}
        self.assertIn("111", games, "a locked pick was dropped from the record")

    def test_a_pick_with_no_readable_first_pitch_locks_immediately(self):
        """Fails CLOSED. The alternative is a pick rewritable forever because
        its timestamp would not parse."""
        pick = _pick(1, "111", NOON, "Take Braves at -110")
        pick["first_pitch_utc"] = "not a timestamp"
        self._publish([pick], NOON - timedelta(hours=12))
        row = card_ledger.published_row("2026-09-11", path=self.path)
        self.assertTrue(row["picks"][0]["locked"])


class TheLedgerStaysAReceipt(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def _publish(self, picks, at):
        return card_ledger.publish(_card(picks), now=at.isoformat(),
                                   path=self.path)

    def test_every_version_is_kept(self):
        """The receipt was never 'we only said it once'. It is 'you can see
        every version and when'."""
        t1 = NIGHT - timedelta(hours=10)
        t2 = NIGHT - timedelta(hours=8)
        self._publish([_pick(1, "222", NIGHT, "First read at -150")], t1)
        self._publish([_pick(1, "222", NIGHT, "Second read at -120",
                             price=-120)], t2)
        versions = card_ledger.published_versions("2026-09-11", path=self.path)
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["picks"][0]["bet"], "First read at -150")
        self.assertEqual(versions[1]["picks"][0]["bet"], "Second read at -120")

    def test_an_unchanged_run_appends_nothing(self):
        """Five runs a day would otherwise write five identical rows and bury
        the versions that matter."""
        t1 = NIGHT - timedelta(hours=10)
        picks = [_pick(1, "222", NIGHT, "Take Yankees at -150")]
        self._publish(picks, t1)
        out = self._publish(picks, t1 + timedelta(minutes=30))
        self.assertTrue(out["already_published"])
        self.assertEqual(
            len(card_ledger.published_versions("2026-09-11", path=self.path)),
            1)

    def test_the_chain_still_verifies_after_several_versions(self):
        for hours in (10, 8, 6):
            self._publish([_pick(1, "222", NIGHT, f"Read at T-{hours}",
                                 price=-100 - hours)],
                          NIGHT - timedelta(hours=hours))
        chain = card_ledger.verify(path=self.path)
        self.assertTrue(getattr(chain, "ok", False))

    def test_the_card_of_record_is_the_newest_version(self):
        for hours in (10, 8, 6):
            self._publish([_pick(1, "222", NIGHT, f"Read at T-{hours}",
                                 price=-100 - hours)],
                          NIGHT - timedelta(hours=hours))
        row = card_ledger.published_row("2026-09-11", path=self.path)
        self.assertEqual(row["picks"][0]["bet"], "Read at T-6")


if __name__ == "__main__":
    unittest.main()
