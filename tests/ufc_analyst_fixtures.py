"""Shared, offline fixtures for the UFC analyst tests.

The world is the data layer's own synthetic one (`tests/test_datasvc_ufc_features.py`:
five fighters, twelve completed bouts, a scheduled card), with ONE odds row of ours that
quotes every market the analyst reads: a moneyline, a rounds total and all six method of
victory prices, fetched at 15:30Z on the day of a main event that starts at 23:00Z. The
packet is built at 16:00Z. Nothing here reads the repo's real data or a network, so no
test that imports it can pass or fail by machine (the `a-test-that-reads-the-disk`
lesson): every store lives in a temporary directory the test owns.

The bout is 9101, Alex Archer (a, -170, +145 current) against Ben Brawler (b), five
rounds, rounds total 4.5 at -110 both ways, every method price quoted.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

from src.analyst import config as config_mod
from src.analyst import ufc_packet
from src.core import odds as odds_math
from tests import analyst_fixtures as mlb_fixtures
from tests.test_datasvc_ufc_features import MAIN_EVENT_START, build_store, odds_row

DATE = "2026-10-10"                      # the event's date (7013 starts 21:00Z, UTC)
EVENT = "7013"
BOUT = "9101"
START = MAIN_EVENT_START                 # "2026-10-10T23:00Z" (ESPN's spelling, no seconds)
START_ISO = "2026-10-10T23:00:00Z"
BUILT_AT = "2026-10-10T16:00:00Z"
ODDS_FETCHED = "2026-10-10T15:30:00Z"
NOW = datetime(2026, 10, 10, 16, 0, 0, tzinfo=timezone.utc)
A, B = "Alex Archer", "Ben Brawler"

CFG = config_mod.validate(dict(config_mod.DEFAULTS))

FakeHttp = mlb_fixtures.FakeHttp
api_response = mlb_fixtures.api_response


def method_odds() -> dict:
    """The data layer's side-method-snapshot nesting, the one the real ESPN rows have."""
    def prices(ko, sub, dec):
        return {"ko_tko_dq": {"open": ko[0], "close": None, "current": ko[1]},
                "submission": {"open": sub[0], "close": None, "current": sub[1]},
                "decision": {"open": dec[0], "close": None, "current": dec[1]}}
    return {"a": prices((300, 280), (800, 750), (350, 330)),
            "b": prices((450, 420), (900, 850), (400, 380))}


def odds(**overrides) -> dict:
    row = odds_row(
        fetched_utc=ODDS_FETCHED,
        a_ml_open=-150, a_ml_current=-170, b_ml_open=130, b_ml_current=145,
        rounds_total=4.5, rounds_total_open=4.5, rounds_total_current=4.5, rounds_total_close=None,
        over_open=-120, over_current=-110, under_open=100, under_current=-110,
        method_odds=method_odds())
    row.update(overrides)
    return row


def make_store(root, rows=None, **kw):
    """The synthetic world with our odds row (or `rows`) on the scheduled main event."""
    return build_store(Path(root), odds=[odds()] if rows is None else rows, **kw)


def packet(store, bout_id=BOUT, built_at=BUILT_AT, **kw) -> dict:
    return ufc_packet.build_packet(store, bout_id, built_at=built_at, cfg=kw.pop("cfg", CFG), **kw)


def item(store, bout_id=BOUT):
    return {"store": store, "bout_id": bout_id, "event_id": EVENT}


def finish_the_bout(store, bout_id=BOUT, **result):
    """Turn a scheduled bout into a finished one with a result, in place."""
    bout = dict(store.bout_by_id()[bout_id])
    bout.update(dict(status="final", winner_id="102", result_method="KO_TKO",
                     result_method_raw="ko-marker", result_detail="ElbowsMarker",
                     end_round=2, end_time_s=77.0, fight_time_s=377.0), **result)
    store.upsert("bouts", [bout])
    return bout


# ---------------------------------------------------------------------------
# a model answer that is valid and verifiable BY CONSTRUCTION
# ---------------------------------------------------------------------------

SUMMARY = (
    "This fight looks like one where the market has done most of the work and I do not want to "
    "talk myself into more. Archer is the favourite on the moneyline and the price already says "
    "so, which leaves Brawler as the side the books are leaving longer. I can see a case for the "
    "underdog in how the two have been scoring, but the sample behind those numbers is small and "
    "the packet tells me so, which keeps my confidence modest. On the total, nothing in the "
    "numbers separates the two ways, so I pass. Every method of victory price is a pass for me: "
    "none of them has a reason behind it beyond its own price, and a single route to victory at a "
    "long price needs more than that. I would change my mind on the underdog only if the price "
    "moved in his direction or a fact about the pair that the packet does not hold turned up, "
    "and I would rather wait than be right by luck.")


def take_other_side_ml(packet: dict) -> dict:
    """A TAKE_OTHER_SIDE on the moneyline, coherent with the packet."""
    market = packet["markets"]["moneyline"]
    other = market["options"][1]
    price, book = other["best"]["price"], other["best"]["book"]
    fair = round(odds_math.american_to_probability(price) + 0.03, 4)
    return {
        "slot_id": "moneyline", "market": "moneyline", "selection": other["selection"],
        "verdict": "TAKE_OTHER_SIDE", "price": price, "book": book, "fair_estimate": fair,
        "confidence": "medium",
        "reasons": [
            {"claim": f"The books make {market['lean']} the favourite, and the price on the other fighter is the longer one.",
             "evidence": [{"path": "markets.moneyline.options[1].best.price", "value": price},
                          {"path": "markets.moneyline.lean", "value": market["lean"]}]},
            {"claim": "The other fighter has finished fewer fights but has been finished less often too.",
             "evidence": [{"path": "sections.fighter_b.values.figures.been_finished_rate.value",
                           "value": packet["sections"]["fighter_b"]["values"]["figures"]["been_finished_rate"]["value"]}]}],
        "pass_price": int(round(odds_math.probability_to_american(fair))),
        "what_would_change_it": "A late price move toward the other fighter, or a change of opponent.",
    }


def pass_call(packet: dict, slot_id: str, claim: str = "The books' own number is the best read here.") -> dict:
    market = packet["markets"][slot_id]
    opt = market["options"][0]
    return {
        "slot_id": slot_id, "market": market["market"], "selection": opt["selection"],
        "verdict": "PASS", "price": opt["best"]["price"], "book": opt["best"]["book"],
        "fair_estimate": None, "confidence": "low",
        "reasons": [{"claim": claim, "evidence": [
            {"path": f"markets.{slot_id}.options[0].implied_probability",
             "value": opt["implied_probability"]}]}],
        "pass_price": None,
        "what_would_change_it": "A price that moves or a fact the packet does not hold.",
    }


def good_output(packet: dict) -> dict:
    calls = []
    for slot in packet["slots"]:
        if slot["slot_id"] == "moneyline":
            calls.append(take_other_side_ml(packet))
        else:
            calls.append(pass_call(packet, slot["slot_id"]))
    return {"summary": SUMMARY, "calls": calls}


def deep(obj):
    return copy.deepcopy(obj)
