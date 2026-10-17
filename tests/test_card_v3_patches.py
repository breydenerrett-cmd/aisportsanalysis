"""Card V3 patches: the behaviour each patch in `docs/decisions/card_v3/` buys.

WHY THIS FILE EXISTS AND WHY MOST OF IT IS `expectedFailure`
-------------------------------------------------------------
`docs/decisions/card_v3/` holds patches against files the V2 registration
fingerprints (`src/analysis/playerprops.py`, `propboard.py`,
`best_bets_card.py`, `card_v2.py`, `card_ledger.py`; PREREG_CARD_V2 11.2 and
section 10). A fingerprint change restarts the counted V2 sample, so the
patches are NOT applied to the committed tree; they are meant for the V3
successor registration (`docs/PREREG_CARD_V3.md`).

Each test below states a behaviour the loss diagnosis
(`docs/research/loss_diagnosis/`) showed is missing from today's code. It
FAILS on today's code, which is the proof it tests the defect, and it PASSES
with the matching patch applied. Until then it is marked `expectedFailure` so
the suite stays green.

TO APPLY A PATCH (V3 only): `git apply docs/decisions/card_v3/<name>.patch`,
then run this file with `CARD_V3_PATCHES_APPLIED=<name>[,<name>...]` (or
`all`) in the environment so the matching tests run as ordinary tests and a
real regression fails the suite; then delete the `pending` decorator on those
tests in the same commit. The patch names are: tb, avg, stale, mlfill,
withdrawn.

A test that passes on today's code AND with the patch (no `pending`) is a
guard on behaviour the patch must not move.
"""

from __future__ import annotations

import os
import unittest

from src.analysis import playerprops


def _applied(name: str) -> bool:
    raw = os.environ.get("CARD_V3_PATCHES_APPLIED", "")
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return "all" in parts or name in parts


def pending(name: str):
    """`expectedFailure` until the named patch is applied (see module doc)."""

    def deco(fn):
        return fn if _applied(name) else unittest.expectedFailure(fn)

    return deco


# ---------------------------------------------------------------------------
# Patch 1: tb_correction.patch
# ---------------------------------------------------------------------------

def _line(pa=4, h=1, doubles=0, triples=0, hr=0, r=0, rbi=0):
    return {"pa": pa, "h": h, "doubles": doubles, "triples": triples,
            "hr": hr, "r": r, "rbi": rbi, "hits_runs_rbi": h + r + rbi}


LEAGUE = {"pa": 100000, "hit": 0.22, "single": 0.15, "double": 0.045,
          "triple": 0.005, "home_run": 0.02, "run": 0.12, "rbi": 0.115}


class TotalBasesOverHalfIsTheHitsEvent(unittest.TestCase):
    """TB >= 1 and H >= 1 are one event. Hits over 0.5 gets the within-game
    correlation (rho) correction; total bases over 0.5 did not, so the card
    priced one event two ways on the same plate appearances. The loss
    diagnosis measured the gap at +2.95 points on 1,163 identical player-games
    (01_estimate_error.md section 3d); `scripts/diagnosis/card_v3_measure.py
    tb` measures the patch on 2024 and on the 2026 forward bets."""

    def setUp(self):
        self.rates = playerprops.batter_rates(
            [_line(pa=4, h=1, doubles=(1 if i % 3 == 0 else 0)) for i in range(100)],
            LEAGUE)

    @pending("tb")
    def test_tb_over_half_equals_hits_over_half_on_identical_inputs(self):
        for pa in (3.2, 4.0, 4.37):
            tb = playerprops.probability_over(
                "batter_total_bases", 0.5, self.rates, pa)
            hits = playerprops.probability_over(
                "batter_hits", 0.5, self.rates, pa)
            self.assertAlmostEqual(tb, hits, places=12,
                                   msg=f"pa={pa}: TB 0.5 {tb:.4f} vs hits 0.5 {hits:.4f}")

    @pending("tb")
    def test_the_equality_holds_through_the_pitcher_factor_and_a_frozen_rho(self):
        """The V2 card passes a frozen rho and a blended pitcher factor; the
        corrected path must honour both, not only the module defaults."""
        for factor, rho in ((1.0, 0.05885), (0.9, 0.05885), (1.12, 0.0)):
            tb = playerprops.probability_over(
                "batter_total_bases", 0.5, self.rates, 4.2, factor, rho=rho)
            hits = playerprops.probability_over(
                "batter_hits", 0.5, self.rates, 4.2, factor, rho=rho)
            self.assertAlmostEqual(tb, hits, places=12)

    @pending("tb")
    def test_price_prop_agrees_end_to_end(self):
        """Through `price_prop`, the entry point the prop board and the card
        use, so a future refactor of `probability_over` cannot hide it."""
        lines = [_line(pa=4, h=1) for _ in range(80)]
        tb = playerprops.price_prop(market="batter_total_bases", line=0.5,
                                    batter_lines=lines, league=LEAGUE,
                                    batting_slot=4)["probability"]
        hits = playerprops.price_prop(market="batter_hits", line=0.5,
                                      batter_lines=lines, league=LEAGUE,
                                      batting_slot=4)["probability"]
        self.assertAlmostEqual(tb, hits, places=12)

    def test_tb_over_1_5_is_not_moved_by_the_patch(self):
        """Guard (passes before AND after): the patch is about the at-least-
        one event only. Over 1.5 stays on the convolution."""
        direct = sum(playerprops.total_bases_distribution(self.rates, 4.2)[2:])
        self.assertAlmostEqual(
            direct,
            playerprops.probability_over("batter_total_bases", 1.5,
                                         self.rates, 4.2),
            places=12)

    def test_hits_over_half_is_not_moved_by_the_patch(self):
        """Guard: the corrected path itself is unchanged. It is the number
        every hits-over-0.5 bet in the V2 ledger was priced with."""
        a = playerprops.probability_over("batter_hits", 0.5, self.rates, 4.2)
        b = playerprops._at_least(self.rates["hit"], 4.2, 1, None)
        self.assertAlmostEqual(a, b, places=12)


if __name__ == "__main__":
    unittest.main()
