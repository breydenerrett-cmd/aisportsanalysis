"""The refusal for an UNGRADED ticket says when it voids (src/hounds/interact/rites.py require_all_settled).

A ticket with no result more than 36 hours after its start is refused with the same code and status as before. What changed is
the message: it now names the ticket and the time the grader voids it (start + capture.void_after_hours from
config/sports_catalog.json), so the owner knows when the wait ends. Runs without FastAPI over a temp database.
"""
from __future__ import annotations

import unittest
from datetime import timedelta

from src.hounds.interact import rites
from src.sports import catalog as sports_catalog
from tests._hounds_rites_fixtures import NOW, RitesCase, ticket


class UngradedTicketMessage(RitesCase):
    def refuse(self, rows):
        dog = self.resolve(self.hound["id"])
        bets = rites.forward_bets(self.hound["id"], rows)
        with self.assertRaises(rites.RiteError) as ctx:
            rites.require_all_settled(dog, bets, NOW)
        return ctx.exception

    def setUp(self):
        super().setUp()
        self.hound = self.dog("Kiwi Pup", sports=["MLB", "NFL"])

    def test_one_ungraded_ticket_names_itself_and_its_void_time(self):
        # Started 70 hours ago: past the 36-hour rule, so it is UNGRADED, and it voids 2 hours from now (72h after start).
        exc = self.refuse(ticket(self.hound["id"], result=None, start_hours_ago=70, now=NOW))
        void_at = NOW + timedelta(hours=2)
        self.assertEqual(exc.code, "open_tickets")
        self.assertEqual(exc.status, 409)
        self.assertEqual(exc.extra.get("open_tickets"), 1)
        self.assertIn("1 ticket still waiting for a grade", str(exc))
        self.assertIn("to win)", str(exc), "the ticket is named by its selection")
        self.assertIn(f"void automatically after {void_at:%A} {void_at:%H:%M} UTC if no result arrives.", str(exc))

    def test_the_void_window_comes_from_the_catalog_not_a_literal(self):
        window = float(sports_catalog.capture_config()["void_after_hours"])
        self.assertEqual(window, 72.0, "the catalog's void window is 72 hours; the message must follow it")
        exc = self.refuse(ticket(self.hound["id"], result=None, start_hours_ago=70, now=NOW))
        start = NOW - timedelta(hours=70)
        self.assertIn(f"{start + timedelta(hours=window):%A} {start + timedelta(hours=window):%H:%M} UTC", str(exc))

    def test_several_ungraded_tickets_name_the_last_void_time(self):
        rows = (ticket(self.hound["id"], day=0, result=None, start_hours_ago=70, now=NOW)
                + ticket(self.hound["id"], day=1, result=None, start_hours_ago=50, now=NOW))
        exc = self.refuse(rows)
        last = NOW - timedelta(hours=50) + timedelta(hours=72)
        self.assertEqual(exc.extra.get("open_tickets"), 2)
        self.assertIn("2 tickets still waiting for a grade. The last of them is void automatically after "
                      f"{last:%A} {last:%H:%M} UTC", str(exc))

    def test_an_open_ticket_keeps_the_old_message(self):
        # Started 2 hours ago: still OPEN under the 36-hour rule, so no void time is claimed for it.
        exc = self.refuse(ticket(self.hound["id"], result=None, start_hours_ago=2, now=NOW))
        self.assertEqual(exc.code, "open_tickets")
        self.assertIn("open ticket", str(exc))
        self.assertNotIn("void", str(exc))


if __name__ == "__main__":
    unittest.main()
