"""V6's forward replication reader refuses to read early and reads only
postings collected after the registration instant.

docs/PREREG_LINEUP_DIRECTION.md and the registry row hold the terms: data
collected after 2026-09-11T20:38:15Z, a floor of 150 usable postings, the
family-wise alpha. The reader here is `--forward` on
scripts/probe_lineup_direction.py; these tests cover the two pure pieces
it rests on, the same way tests/test_lineup_direction.py covers the rest.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tests.test_lineup_direction import probe

REG = probe.REGISTERED_AT


def _obs(at, **extra):
    row = {"game_pk": 1, "after": 0.01, "expected": -1, "at": at}
    row.update(extra)
    return row


class OnlyPostingsAfterRegistrationAreRead(unittest.TestCase):

    def test_before_and_at_the_instant_are_discovery_data(self):
        rows = [_obs(REG - timedelta(seconds=1)), _obs(REG),
                _obs(REG + timedelta(seconds=1), game_pk=2)]
        kept = probe.forward_only(rows)
        self.assertEqual([o["game_pk"] for o in kept], [2])

    def test_a_naive_timestamp_is_read_as_utc(self):
        naive_after = (REG + timedelta(hours=1)).replace(tzinfo=None)
        naive_before = (REG - timedelta(hours=1)).replace(tzinfo=None)
        kept = probe.forward_only([_obs(naive_after, game_pk=7),
                                   _obs(naive_before, game_pk=8)])
        self.assertEqual([o["game_pk"] for o in kept], [7])

    def test_a_posting_with_no_time_is_never_read(self):
        self.assertEqual(probe.forward_only([_obs(None)]), [])

    def test_the_cutoff_is_the_registration_instant(self):
        self.assertEqual(REG, datetime(2026, 9, 11, 20, 38, 15, tzinfo=timezone.utc))


class TheFloorIsNotLowered(unittest.TestCase):

    def test_pending_below_the_floor_read_at_it(self):
        self.assertEqual(probe.FORWARD_FLOOR, 150)
        self.assertEqual(probe.forward_state(149), "PENDING")
        self.assertEqual(probe.forward_state(150), "READ")
        self.assertEqual(probe.forward_state(0), "PENDING")

    def test_observations_now_carry_when_the_posting_landed(self):
        """`_observations` must stamp `at`, or the forward filter has
        nothing to filter on and reads everything."""
        import inspect
        source = inspect.getsource(probe._observations)
        self.assertIn('"at": anchor', source)


if __name__ == "__main__":
    unittest.main()
