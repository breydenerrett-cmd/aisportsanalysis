"""Totals Terrier: the house run model's total, at the main half-point line."""

from __future__ import annotations

from typing import List

from src.hounds.pack import professor_paws
from src.hounds.pack.base import Context, Hound, Selection

SHRINK = 0.5
GAP = 0.030


class TotalsTerrier(Hound):
    id = "totals_terrier"
    name = "Totals Terrier"
    tagline = "Smells runs."
    category = "stats"
    style = "model total vs market total"
    sports = ("mlb",)
    markets = ("total",)
    who_decided = "model"
    RULE = ("MLB game total, main line, half-point lines only. Same house run model and inputs as "
            "Professor Paws. Shrink its Over probability 50% toward the de-vigged consensus. Bet the Over "
            "if the shrunk probability beats the consensus Over by 3.0 points or more, the Under if it "
            "trails by 3.0 points or more.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if ctx.sport != "mlb":
            return []
        mb = (board.get("markets") or {}).get("total")
        if not mb or mb["line"] is None or abs(mb["line"] * 2 - round(mb["line"] * 2)) > 1e-9 \
                or float(mb["line"]).is_integer():
            return []
        m = professor_paws.model(ctx, mb["line"])
        if not m or m.get("p_over") is None:
            return []
        fair_over = mb["sides"]["over"]["fair"]
        p = SHRINK * m["p_over"] + (1 - SHRINK) * fair_over
        gap = p - fair_over
        if abs(gap) < GAP:
            return []
        side = "over" if gap > 0 else "under"
        reason = (f"Model expects {m['expected_total']:.2f} runs (Over {mb['line']:g} at {m['p_over']:.3f}, "
                  f"shrunk {p:.3f}) vs consensus Over {fair_over:.3f}.")
        return [Selection("total", side, round(abs(gap), 6), reason)]


HOUND = TotalsTerrier()
