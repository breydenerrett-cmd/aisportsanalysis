"""Shared, offline fixtures for the NFL analyst tests.

One small synthetic game (BUF at KC, week 8 of 2025, kickoff 20:25Z on 2025-10-26) on the synthetic
league of tests/_nfl_world.py, the odds rows the multibook store would hold for it, a canned model
answer built FROM the packet (so it is valid by construction), and the helpers the tests share.
Nothing here reads the repo's data or touches a network, so no test that imports it can pass or
fail by machine (the `a-test-that-reads-the-disk` lesson).
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

from src.analyst import config as config_mod
from src.analyst import nfl_packet
from src.core import odds as odds_math
from tests import _nfl_world as W

GAME_ID = "2025_08_BUF_KC"
DATE = "2025-10-26"
KICKOFF = "2025-10-26T20:25:00Z"
BUILT_AT = "2025-10-26T17:25:00Z"                 # three hours before kickoff
CAPTURED = "2025-10-26T16:51:16.161446+00:00"
NOW = datetime(2025, 10, 26, 17, 25, 0, tzinfo=timezone.utc)

CFG = config_mod.validate(dict(config_mod.DEFAULTS))

BOOKS = ("draftkings", "fanduel", "betmgm")


def make_store(root, *, injuries: bool = True):
    """The synthetic league under `root`, with a week-8 injury report for the game when asked."""
    store = W.build_world(Path(root))
    if injuries:
        games = {g["game_id"]: g for g in store.games}
        g = games[GAME_ID]
        store.upsert("injuries", [
            W._injury(GAME_ID, g, "00-KCWR1", "KC", "Kay See", "WR", "WR", "out", "dnp", None, "Hamstring"),
            W._injury(GAME_ID, g, "00-BUFQB1", "BUF", "Bee Quarterback", "QB", "QB", "questionable", "limited",
                      None, "Shoulder"),
        ])
    return store


def odds_rows(*, ml=None, spread=None, total=None, captured=CAPTURED, commence=KICKOFF) -> list:
    """BUF at KC rows as the multibook store spells them: NFL rows carry `sport`; the moneyline has no
    `market` key. KC is the home favourite by 3.5."""
    ml = ml or {"draftkings": (175, -210), "fanduel": (170, -205), "betmgm": (180, -215)}
    spread = spread or {"draftkings": (-110, -110), "fanduel": (-108, -112), "betmgm": (-112, -108)}
    total = total or {"draftkings": (-105, -115), "fanduel": (-108, -112), "betmgm": (-110, -110)}
    base = {"observed_utc": captured, "commence_time": commence, "away_team": "Buffalo Bills",
            "home_team": "Kansas City Chiefs", "sport": "nfl"}
    rows = []
    for book, (away, home) in ml.items():
        rows.append(dict(base, book=book, away_price=away, home_price=home))
    for book, (away, home) in spread.items():
        rows.append(dict(base, book=book, market="spreads", away_line="3.5", away_price=away,
                         home_line="-3.5", home_price=home))
    for book, (over, under) in total.items():
        rows.append(dict(base, book=book, market="totals", total="47.5", over_price=over, under_price=under))
    return rows


def build(store, *, built_at=BUILT_AT, rows=None, game_id=GAME_ID) -> dict:
    return nfl_packet.build_packet(store, game_id, built_at=built_at,
                                   multibook_rows=odds_rows() if rows is None else rows, cfg=CFG)


# ---------------------------------------------------------------------------
# a model answer that is valid and verifiable BY CONSTRUCTION
# ---------------------------------------------------------------------------

SUMMARY = (
    "The home side is the better team on the numbers and the books know it, which is why its moneyline "
    "price is too short to touch. I would not lay it. The road side has the longer price and the recent "
    "games are closer than the market suggests, so the one place I lean away from the crowd is the road "
    "moneyline, and I hold that loosely. The spread asks for a field goal and a half, and nothing in the "
    "data tells me that number is wrong, so I pass on it. The total is the same story: the scoring "
    "figures for both sides are in line with the number, so I pass there too. Weather is not in the data "
    "and the injury report only counts players without telling me how much each one matters, so I keep "
    "my confidence modest. If the quarterback situation changed or the number moved, I would look again, "
    "but until then the market is probably about right and I would rather say so than force a view."
)


def value(packet: dict, path: str):
    ok, found = nfl_packet.resolve_path(packet, path)
    assert ok, (path, found)
    return found


def take_other_side_ml(packet: dict) -> dict:
    """A TAKE_OTHER_SIDE on the moneyline (the road underdog), coherent with the packet."""
    market = packet["markets"]["moneyline"]
    other = market["options"][1]
    price, book = other["best"]["price"], other["best"]["book"]
    fair = round(odds_math.american_to_probability(price) + 0.03, 4)
    pass_price = int(round(odds_math.probability_to_american(fair)))
    home_pf = value(packet, "sections.home.values.form.last_3.points_for_per_game")
    away_pf = value(packet, "sections.away.values.form.last_3.points_for_per_game")
    return {
        "slot_id": "moneyline", "market": "moneyline", "selection": other["selection"],
        "verdict": "TAKE_OTHER_SIDE", "price": price, "book": book, "fair_estimate": fair,
        "confidence": "medium",
        "reasons": [
            {"claim": f"The books make {market['lean']} the favourite, and the road price is the longer one.",
             "evidence": [{"path": "markets.moneyline.options[1].best.price", "value": price},
                          {"path": "markets.moneyline.lean", "value": market["lean"]}],
             "derived": []},
            {"claim": f"The road side scored {away_pf:g} points a game over its last three.",
             "evidence": [{"path": "sections.away.values.form.last_3.points_for_per_game", "value": away_pf}],
             "derived": []}],
        "pass_price": pass_price,
        "what_would_change_it": "A change at quarterback, or a star player ruled out on the injury report.",
        "case_against": {
            "claim": f"The home side scored {home_pf:g} points a game over its last three, more than the road side.",
            "evidence": [{"path": "sections.home.values.form.last_3.points_for_per_game", "value": home_pf},
                         {"path": "sections.away.values.form.last_3.points_for_per_game", "value": away_pf}],
            "derived": []},
    }


def pass_call(packet: dict, slot_id: str, claim: str = "The books' own number is the best read here.") -> dict:
    market = packet["markets"][slot_id]
    opt = market["options"][0]
    return {
        "slot_id": slot_id, "market": market["market"], "selection": opt["selection"],
        "verdict": "PASS", "price": opt["best"]["price"], "book": opt["best"]["book"],
        "fair_estimate": None, "confidence": "low",
        "reasons": [{"claim": claim, "evidence": [
            {"path": f"markets.{slot_id}.options[0].fair_probability", "value": opt["fair_probability"]}],
            "derived": []}],
        "pass_price": None,
        "what_would_change_it": "A change at quarterback or a number that moves.",
        "case_against": None,
    }


def good_output(packet: dict) -> dict:
    calls = []
    for slot in packet["slots"]:
        calls.append(take_other_side_ml(packet) if slot["slot_id"] == "moneyline"
                     else pass_call(packet, slot["slot_id"]))
    return {"summary": SUMMARY, "summary_derived": [], "calls": calls}


def deep(obj):
    return copy.deepcopy(obj)
