"""Numerology Newfie: reads the numbers, not the games. ENTERTAINMENT ONLY: nobody claims this works."""

from __future__ import annotations

from typing import List

from src.hounds.pack.base import Context, Hound, Selection, side_info


def gematria(name: str) -> int:
    """English ordinal gematria: A=1 .. Z=26, letters only, case ignored."""
    return sum(ord(c) - 96 for c in (name or "").lower() if "a" <= c <= "z")


def digital_root(n: int) -> int:
    return 0 if n <= 0 else 1 + (n - 1) % 9


def date_number(day: str) -> int:
    return digital_root(sum(int(c) for c in day if c.isdigit()))


class NumerologyNewfie(Hound):
    id = "numerology_newfie"
    name = "Numerology Newfie"
    tagline = "Reads the numbers, not the games. For fun."
    category = "esoteric"
    style = "gematria (entertainment)"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    RULE = ("For fun, moneyline, MLB and NFL. Team number = digital root of the English ordinal gematria "
            "(A=1..Z=26) of the odds feed's full team name. Date number = digital root of the digits of the "
            "game's date. Bet the club whose number is closer to the date number; equal distance passes.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if not side_info(board, "moneyline", "home"):
            return []
        d = date_number(ctx.date)
        h, a = digital_root(gematria(ctx.home_name)), digital_root(gematria(ctx.away_name))
        dh, da = abs(h - d), abs(a - d)
        if dh == da:
            return []
        side = "home" if dh < da else "away"
        reason = (f"Date {ctx.date} reduces to {d}; {ctx.home_name} reduce to {h}, {ctx.away_name} to {a}. "
                  f"For fun only.")
        return [Selection("moneyline", side, 0.0, reason)]


HOUND = NumerologyNewfie()
