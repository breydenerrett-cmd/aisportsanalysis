"""A page render may not allocate a container's worth of memory.

WHY THIS FILE EXISTS
--------------------
Staging runs on 512 MB (`deploy/fly.staging.toml`). On 2026-09-10 the card
endpoint took it down twice in one afternoon, and both times the deploy that
shipped the fault reported healthy on the way in:

  * `run_line_rows` called `snapshots.read_multibook()`, which parses a 38 MB
    JSONL into 119,000 dicts -- **174 MB** per request. 503.
  * Caching the RESULT did not help, because the first request still paid
    for the whole parse. 502.

Neither was visible to `/health`, which touches no store, and neither was
visible to the unit suite, which asserts what a function RETURNS and never
what it costs to get there.

So this file asserts the cost. The budgets are deliberately far below what
would actually break a 512 MB machine -- the point is to catch the day a
whole-store read comes back, not to shave megabytes. A failure here means
someone reintroduced "read it all, then filter", and the fix is
`snapshots.iter_multibook` or an equivalent stream.

Measured after the fix, on the real stores: run-line board 2.5 MB, relief
rates 29.5 MB (one 4.2 MB log, parsed once per process).
"""

from __future__ import annotations

import gc
import os
import tracemalloc
import unittest

from src.pipeline import snapshots

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Generous. The measured figures are 2.5 MB and 29.5 MB; a whole-store read
# is 174 MB. Anything between is a regression worth looking at and anything
# above these is the bug coming back.
RUN_LINE_BUDGET_MB = 40
RELIEF_BUDGET_MB = 60

# The date does not matter to the cost -- the store is scanned either way --
# so this is simply a date the captured store covers.
A_CAPTURED_DATE = "2026-09-09"


def _peak_mb(fn):
    gc.collect()
    tracemalloc.start()
    try:
        fn()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak / 1e6


def _store_present():
    return os.path.exists(os.path.join(REPO, snapshots.DEFAULT_MULTIBOOK_PATH))


@unittest.skipUnless(_store_present(),
                     "the multi-book store is not in this checkout")
class ThePageDoesNotEatTheContainer(unittest.TestCase):
    def setUp(self):
        from src.report import card as card_mod
        self.card = card_mod
        # Caches would make a second run free and hide a regression, so each
        # test measures a COLD call.
        card_mod._RUNLINE_CACHE = type(card_mod._RUNLINE_CACHE)(
            ttl_s=card_mod.RUNLINE_CACHE_TTL_S)
        card_mod._RELIEF_CACHE.clear()

    def test_building_the_run_line_board_stays_within_budget(self):
        peak = _peak_mb(lambda: self.card.run_line_rows(A_CAPTURED_DATE))
        self.assertLess(
            peak, RUN_LINE_BUDGET_MB,
            f"one run-line board allocated {peak:.1f} MB. A whole-store read "
            f"is ~174 MB and took staging down twice on 2026-09-10 -- see "
            f"snapshots.iter_multibook, and stream rather than materialise.")

    def test_the_relief_rates_stay_within_budget(self):
        peak = _peak_mb(lambda: self.card.relief_rates_for(A_CAPTURED_DATE))
        self.assertLess(
            peak, RELIEF_BUDGET_MB,
            f"one relief-rate build allocated {peak:.1f} MB")

    def test_a_second_call_is_effectively_free(self):
        """The cache is doing its job, which is the difference between one
        expensive request and one expensive request per viewer."""
        self.card.run_line_rows(A_CAPTURED_DATE)
        peak = _peak_mb(lambda: self.card.run_line_rows(A_CAPTURED_DATE))
        self.assertLess(peak, 1.0,
                        f"a warm run-line board still allocated {peak:.1f} MB")

    def test_the_streaming_read_beats_the_whole_store_read_by_an_order(self):
        """Directly comparative, so the test states the fact it is
        protecting rather than an arbitrary threshold."""
        streamed = _peak_mb(
            lambda: sum(1 for _ in snapshots.iter_multibook(market="spreads")))
        whole = _peak_mb(snapshots.read_multibook)
        self.assertLess(
            streamed * 10, whole,
            f"streaming ({streamed:.1f} MB) is no longer meaningfully "
            f"cheaper than reading the whole store ({whole:.1f} MB)")


if __name__ == "__main__":
    unittest.main()
