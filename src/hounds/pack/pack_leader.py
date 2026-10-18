"""Pack Leader: goes with the pack (a majority of the stats, history and market hounds)."""

from __future__ import annotations

from typing import List

from src.hounds.pack import (elimination_basset, gridiron_greyhound, jetlag_jack, professor_paws,
                             relief_retriever, stale_bread_beagle, steamy_setter)
from src.hounds.pack.base import Context, Hound, Selection, side_info

VOTERS = (professor_paws.HOUND, relief_retriever.HOUND, gridiron_greyhound.HOUND,
          elimination_basset.HOUND, jetlag_jack.HOUND, steamy_setter.HOUND, stale_bread_beagle.HOUND)
MIN_VOTES = 2


def votes(board, ctx: Context) -> dict:
    out = {"home": [], "away": []}
    for hound in VOTERS:
        if not hound.applies_to(ctx.sport):
            continue
        for sel in hound.pick(board, ctx):
            if sel.market in ("moneyline", "spread") and sel.side in out:
                out[sel.side].append(hound.id)
    return out


class PackLeader(Hound):
    id = "pack_leader"
    name = "Pack Leader"
    tagline = "Goes with the pack."
    category = "mixed"
    style = "ensemble vote"
    sports = ("mlb", "nfl")
    markets = ("moneyline",)
    RULE = ("Moneyline, MLB and NFL. Voters: Professor Paws, Relief Retriever, Gridiron Greyhound, "
            "Elimination Basset, Jet-Lag Jack, Steamy Setter and Stale-Bread Beagle (moneyline and spread "
            "picks only), asked about this game before any daily cap. Bet a club's moneyline when it has 2 "
            "or more votes and the other club has none.")

    def pick(self, board, ctx: Context) -> List[Selection]:
        if not side_info(board, "moneyline", "home"):
            return []
        v = votes(board, ctx)
        for side in ("home", "away"):
            opp = "away" if side == "home" else "home"
            if len(v[side]) >= MIN_VOTES and not v[opp]:
                team = ctx.home_name if side == "home" else ctx.away_name
                return [Selection("moneyline", side, float(len(v[side])),
                                  f"{len(v[side])} hounds back {team}: {', '.join(v[side])}; none oppose.")]
        return []


HOUND = PackLeader()
