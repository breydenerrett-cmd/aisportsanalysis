"""Lunar Lab: howls at the moon. ENTERTAINMENT ONLY: nobody claims this works."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from src.hounds.pack.base import Context, Hound, Selection

REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
SYNODIC_DAYS = 29.530588853
WINDOW = 1.5
HALF = SYNODIC_DAYS / 2.0


def moon_age(moment: datetime) -> float:
    """Days since the last new moon, from the mean synodic month (no network)."""
    return ((moment - REFERENCE_NEW_MOON).total_seconds() / 86400.0) % SYNODIC_DAYS


def phase(moment: datetime) -> str:
    age = moon_age(moment)
    if abs(age - HALF) <= WINDOW:
        return "full"
    if age <= WINDOW or age >= SYNODIC_DAYS - WINDOW:
        return "new"
    return "other"


class LunarLab(Hound):
    id = "lunar_lab"
    name = "Lunar Lab"
    tagline = "Howls at the moon. For fun."
    category = "esoteric"
    style = "moon phase (entertainment)"
    sports = ("mlb", "nfl")
    markets = ("total",)
    RULE = ("For fun, game total, MLB and NFL. Moon age at the start = days since the 2000-01-06 18:14 UTC "
            "new moon, modulo 29.530588853. Within 1.5 days of full moon bet the Over; within 1.5 days of new "
            "moon bet the Under; otherwise pass.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        mb = (board.get("markets") or {}).get("total")
        if not mb:
            return []
        ph = phase(ctx.start)
        if ph == "other":
            return []
        side = "over" if ph == "full" else "under"
        reason = f"Moon age {moon_age(ctx.start):.2f} days at first pitch/kickoff: {ph} moon. For fun only."
        return [Selection("total", side, 0.0, reason)]


HOUND = LunarLab()
