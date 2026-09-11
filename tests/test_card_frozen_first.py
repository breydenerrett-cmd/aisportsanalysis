"""A published card must not rebuild the slate to serve a row it already has.

WHAT THIS COST
--------------
`api/card.py::_build_payload` ran `_build_entries` -- a live schedule fetch
plus a full slate build -- and then `build_opportunities` over the result,
before handing both to `card_mod.card_for_date`.

`card_for_date` serves the FROZEN row whenever one exists, and in that branch
it reads neither argument. So on every request for a date whose card is
published -- every request for today's card, all day, from every visitor --
the endpoint built a slate and a price board and discarded them.

From the staging container's own log on 2026-09-10:

    GET /card/{date}  status=200  latency_ms=15260.3

Fifteen seconds of a one-CPU machine for a result already on disk. It starved
/health past Fly's five-second check, Fly pulled the machine out of rotation,
and visitors got 503s from an app that was alive and working.

WHAT IS TESTED, AND WHY IT IS NOT A TIMING TEST
-----------------------------------------------
The property is "the expensive builders are NOT CALLED", which is exact.
Timing the endpoint would pass or fail by machine and would still pass on a
version that called them and happened to be fast on a developer laptop.

Both builders are replaced with spies that raise if touched, so a regression
fails loudly and names itself rather than quietly costing fifteen seconds
again.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

try:
    import api.card as apicard
except ImportError:  # pragma: no cover - CI installs no fastapi
    apicard = None


FROZEN = {
    "picks": [{"bet": "Take Yankees -1.5 at -149"}],
    "filled": 1,
    "frozen": True,
    "frozen_at": "2026-09-10T14:36:00+00:00",
    "rule": "rule text",
    "basis": "basis text",
    "disclaimer": "disclaimer text",
}


class _Exploded(Exception):
    pass


@unittest.skipIf(apicard is None, "fastapi not installed")
class AFrozenCardCostsOneLedgerRead(unittest.TestCase):

    def setUp(self):
        self._saved = (apicard.card_mod.frozen_card,
                       apicard._build_entries,
                       apicard.opportunities_mod.build_opportunities,
                       apicard._record_page_view)
        apicard._record_page_view = lambda *a, **k: None

    def tearDown(self):
        (apicard.card_mod.frozen_card, apicard._build_entries,
         apicard.opportunities_mod.build_opportunities,
         apicard._record_page_view) = self._saved

    def _arm(self, frozen):
        apicard.card_mod.frozen_card = lambda date: (
            dict(frozen) if frozen is not None else None)

        def _boom_entries(*_a, **_k):
            raise _Exploded("_build_entries was called for a frozen card")

        def _boom_opps(*_a, **_k):
            raise _Exploded("build_opportunities was called for a frozen card")

        apicard._build_entries = _boom_entries
        apicard.opportunities_mod.build_opportunities = _boom_opps

    def test_neither_expensive_builder_runs(self):
        """THE ONE THAT MATTERS. Both spies raise; reaching either fails."""
        self._arm(FROZEN)
        payload = apicard._build_payload("2026-09-10", None, "card")
        self.assertTrue(payload["frozen"])
        self.assertEqual(len(payload["picks"]), 1)

    def test_the_card_itself_is_unchanged(self):
        self._arm(FROZEN)
        payload = apicard._build_payload("2026-09-10", None, "card")
        self.assertEqual(payload["picks"], FROZEN["picks"])
        self.assertEqual(payload["rule"], FROZEN["rule"])
        self.assertEqual(payload["disclaimer"], FROZEN["disclaimer"])
        self.assertEqual(payload["date"], "2026-09-10")
        self.assertIsNotNone(payload.get("model_basis"))

    def test_freshness_is_still_present_and_describes_the_freeze(self):
        """Consumers read `freshness` on every card payload. A frozen row is
        exactly as fresh as it promised to be, so `stale` is False and
        `built_at` is the publish instant -- NOT the price age, which the page
        warns about separately. Conflating the two would either cry stale
        about a card doing its job, or hide an old quote behind a fresh build
        time."""
        self._arm(FROZEN)
        payload = apicard._build_payload("2026-09-10", None, "card")
        fresh = payload.get("freshness")
        self.assertIsInstance(fresh, dict)
        self.assertFalse(fresh["stale"])
        self.assertIsNone(fresh["stale_reason"])
        self.assertEqual(fresh["built_at"], FROZEN["frozen_at"])
        self.assertIsInstance(fresh["age_s"], float)

    def test_an_unparseable_publish_time_does_not_crash_the_card(self):
        """Absent is not zero, and a bad timestamp is not an outage. The card
        still serves; only the age is unknown."""
        self._arm(dict(FROZEN, frozen_at="not a timestamp"))
        payload = apicard._build_payload("2026-09-10", None, "card")
        self.assertTrue(payload["frozen"])
        self.assertIsNone(payload["freshness"]["age_s"])

    def test_a_date_with_no_frozen_card_still_builds_live(self):
        """The live branch must be untouched -- a date nobody has published
        genuinely has to be built, and silently serving nothing would be
        worse than the fifteen seconds this change removes."""
        apicard.card_mod.frozen_card = lambda date: None
        called = {"entries": 0, "opps": 0}

        def _entries(date, **_k):
            called["entries"] += 1
            return [], [], {"stale": False}

        def _opps(entries, **_k):
            called["opps"] += 1
            return {"rows": []}

        apicard._build_entries = _entries
        apicard.opportunities_mod.build_opportunities = _opps
        saved_live = apicard.card_mod.card_for_date
        apicard.card_mod.card_for_date = lambda *a, **k: {"picks": [],
                                                          "frozen": False}
        try:
            payload = apicard._build_payload("2099-01-01", None, "card")
        finally:
            apicard.card_mod.card_for_date = saved_live
        self.assertEqual(called["entries"], 1)
        self.assertEqual(called["opps"], 1)
        self.assertFalse(payload["frozen"])


if __name__ == "__main__":
    unittest.main()
