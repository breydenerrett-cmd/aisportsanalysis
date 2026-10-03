"""Shared, offline fixtures for the AI analyst tests.

One small synthetic game (NYY at TB, first pitch 22:30Z on 2026-10-03), the
price rows the stores would hold for it, a canned model answer built FROM the
packet (so it is valid by construction), and a fake HTTP caller. Nothing here
reads the repo's data or touches a network, so no test that imports it can
pass or fail by machine (the `a-test-that-reads-the-disk` lesson).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from src.analyst import config as config_mod
from src.analyst import packet as packet_mod
from src.core import odds as odds_math

DATE = "2026-10-03"
FIRST_PITCH = "2026-10-03T22:30:00Z"
BUILT_AT = "2026-10-03T18:00:00Z"
CAPTURED = "2026-10-03T16:51:16.161446+00:00"
NOW = datetime(2026, 10, 3, 18, 0, 0, tzinfo=timezone.utc)

CFG = config_mod.validate(dict(config_mod.DEFAULTS))


def payload(state="pending", with_scores=False) -> dict:
    game = {
        "game_pk": 849835, "date": DATE, "start_time_utc": FIRST_PITCH, "state": state,
        "detailed_state": "Scheduled", "game_type": "D", "venue": "Tropicana Field",
        "away_team": "NYY", "home_team": "TB",
        "away_probable": "Gerrit Cole", "home_probable": "Drew Rasmussen",
        "away_score": None, "home_score": None, "winner": None, "total_runs": None,
        "first_five": {"complete": False},
    }
    if with_scores:
        game.update(away_score=9, home_score=1, winner="NYY", total_runs=10)
    return {"advanced": {
        "game_id": "NYY-TB-2026-10-03-1", "away_team": "NYY", "home_team": "TB", "game": game,
        "information_time": "2026-10-03T17:37:47.063006+00:00",
        "sections": {
            "teams": {"away_win_pct": 0.5677, "home_win_pct": 0.6026, "away_last10_wins": 6,
                      "home_last10_wins": 7, "away_sample_is_thin": False,
                      "home_sample_is_thin": False},
            "starters": {"away_sp_known": True, "home_sp_known": True, "away_sp_era": 3.4054,
                         "home_sp_era": 2.8761, "away_sp_fip": 3.8602, "home_sp_fip": 2.9911,
                         "away_sp_thin": False, "home_sp_thin": False, "diff_sp_fip": -0.8691},
            "park": {"name": "Tropicana Field", "lat": 27.7, "lon": -82.6, "roof": "fixed"},
            "weather": {"observed_utc": "2026-10-03T22:00", "temp_f": 86.4, "wind_mph": 4.5},
            "splits": {"away": {"record": {"as_of": "2026-09-08T20:37:57Z",
                                           "splits": {"Away Games": {"avg": 0.265}}}}},
            "price_improvement": {"sides": {}}, "market": {"markets": {}},
        },
        "gaps": {"lineups": "lineup not posted yet, or not fetched",
                 "news": "no injured-list moves, call-ups or trades"},
    }}


def _ml(book, away, home):
    return {"observed_utc": CAPTURED, "book": book, "away_team": "New York Yankees",
            "home_team": "Tampa Bay Rays", "away_price": away, "home_price": home}


def multibook_rows(home_ml=(-135, -127, -132), away_ml=(115, 117, 112)) -> list:
    books = ("draftkings", "fanduel", "betmgm")
    rows = [_ml(b, a, h) for b, a, h in zip(books, away_ml, home_ml)]
    for b, hp, ap in zip(books, (165, 170, 180), (-200, -195, -220)):
        rows.append({"observed_utc": CAPTURED, "book": b, "market": "spreads",
                     "home_line": "-1.5", "home_price": hp, "away_line": "1.5", "away_price": ap})
    for b, o, u in zip(books, (-105, -108, -110), (-115, -112, -110)):
        rows.append({"observed_utc": CAPTURED, "book": b, "market": "totals", "total": "7.0",
                     "over_price": o, "under_price": u})
    return rows


def team_total_rows() -> list:
    rows = []
    for team in ("New York Yankees", "Tampa Bay Rays"):
        for book, over, under in (("draftkings", -120, 100), ("fanduel", -115, -105)):
            for side, price in (("Over", over), ("Under", under)):
                rows.append({"observed_utc": CAPTURED, "book": book, "market": "team_totals",
                             "team": team, "line": "3.5", "side": side, "price": price})
    return rows


def batter_prop_rows() -> list:
    rows = []
    for player, market, line, prices in (
            ("Junior Caminero", "batter_hits", "0.5", {"Over": (-220, -230), "Under": (170, 175)}),
            ("Ben Rice", "batter_total_bases", "1.5", {"Over": (130, 125), "Under": (-160, -155)}),
            ("Jazz Chisholm Jr.", "batter_home_runs", "0.5", {"Over": (320, 330)})):
        for side, (p1, p2) in prices.items():
            for book, price in (("draftkings", p1), ("fanduel", p2)):
                rows.append({"observed_utc": CAPTURED, "book": book, "market": market,
                             "player": player, "line": line, "side": side, "price": price})
    return rows


def pitcher_prop_rows() -> list:
    return [{"observed_utc": CAPTURED, "book": b, "market": "pitcher_strikeouts",
             "player": "Gerrit Cole", "point": 6.5, "over_price": o, "under_price": u}
            for b, o, u in (("draftkings", -118, -104), ("fanduel", -115, -108))]


def prop_board() -> list:
    return [{"player": "Junior Caminero", "market": "batter_hits", "line": 0.5, "side": "Over",
             "probability": 0.7636, "market_probability": 0.68, "season_rate": 0.2593,
             "season_games": 27, "expected_pa": 4.222, "batting_slot": 3},
            {"player": "Ben Rice", "market": "batter_total_bases", "line": 1.5, "side": "Under",
             "probability": 0.58, "market_probability": 0.56, "expected_pa": 4.1}]


def build(*, state="pending", with_scores=False, built_at=BUILT_AT, **overrides) -> dict:
    kwargs = dict(
        multibook_rows=multibook_rows(), team_total_rows=team_total_rows(),
        batter_prop_rows=batter_prop_rows(), pitcher_prop_rows=pitcher_prop_rows(),
        prop_board=prop_board(),
        team_names={"away": "New York Yankees", "home": "Tampa Bay Rays"},
        section_as_of={"teams": "2026-10-02", "starters": "2026-10-02"}, cfg=CFG)
    kwargs.update(overrides)
    return packet_mod.build_packet(payload(state, with_scores), built_at=built_at, **kwargs)


# ---------------------------------------------------------------------------
# a model answer that is valid and verifiable BY CONSTRUCTION
# ---------------------------------------------------------------------------

SUMMARY = (
    "This game looks like the market has it about right and I do not want to talk myself into "
    "more. The home side is the lean on the moneyline and the price already reflects the "
    "starting pitching gap, so there is nothing here the books do not know. The run line asks "
    "for a lot at a short price and I would rather pass than lay it. On the total, the books are "
    "split enough that I see no reason to pick a side. Lineups are not posted yet, which matters "
    "for every player prop, so I am passing on those too, and I would rather be wrong by waiting "
    "than right by luck. The one place I lean away from the crowd is the road side on the "
    "moneyline, because the price is longer than the numbers justify, but I hold that loosely and "
    "will change it the moment a lineup shows a surprise or a price moves against it, because "
    "nothing in this packet is strong enough to be sure about.")


def take_other_side_ml(packet: dict) -> dict:
    """A TAKE_OTHER_SIDE call on the moneyline, coherent with the packet."""
    market = packet["markets"]["moneyline"]
    other = market["options"][1]
    price, book = other["best"]["price"], other["best"]["book"]
    fair = round(odds_math.american_to_probability(price) + 0.03, 4)
    pass_price = int(round(odds_math.probability_to_american(fair)))
    return {
        "slot_id": "moneyline", "market": "moneyline", "selection": other["selection"],
        "verdict": "TAKE_OTHER_SIDE", "price": price, "book": book, "fair_estimate": fair,
        "confidence": "medium",
        "reasons": [
            {"claim": f"The books make {market['lean']} the favourite, and the road price is the longer one.",
             "evidence": [{"path": "markets.moneyline.options[1].best.price", "value": price},
                          {"path": "markets.moneyline.lean", "value": market["lean"]}]},
            {"claim": "The starters are closer than the home price suggests.",
             "evidence": [{"path": "sections.starters.values.away_sp_fip", "value": 3.8602},
                          {"path": "sections.starters.values.home_sp_fip", "value": 2.9911}]}],
        "pass_price": pass_price,
        "what_would_change_it": "A lineup that sits the road side's best hitters, or the price shortening.",
    }


def pass_call(packet: dict, slot_id: str, claim: str = "The books' own number is the best read here.") -> dict:
    market = packet["markets"][slot_id]
    opt = market["options"][0]
    return {
        "slot_id": slot_id, "market": market["market"], "selection": opt["selection"],
        "verdict": "PASS", "price": opt["best"]["price"], "book": opt["best"]["book"],
        "fair_estimate": None, "confidence": "low",
        "reasons": [{"claim": claim, "evidence": [
            {"path": f"markets.{slot_id}.options[0].fair_probability",
             "value": opt["fair_probability"]}]}],
        "pass_price": None,
        "what_would_change_it": "A posted lineup or a price that moves.",
    }


def good_output(packet: dict) -> dict:
    calls = []
    for slot in packet["slots"]:
        if slot["slot_id"] == "moneyline":
            calls.append(take_other_side_ml(packet))
        else:
            calls.append(pass_call(packet, slot["slot_id"]))
    return {"summary": SUMMARY, "calls": calls}


# ---------------------------------------------------------------------------
# a fake HTTP caller
# ---------------------------------------------------------------------------

def api_response(output, usage=None, *, stop_reason="end_turn", msg_id="msg_test") -> bytes:
    text = output if isinstance(output, str) else json.dumps(output)
    return json.dumps({
        "id": msg_id, "type": "message", "model": "claude-sonnet-5-5", "role": "assistant",
        "stop_reason": stop_reason,
        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
        "usage": usage or {"input_tokens": 10000, "output_tokens": 5000},
    }).encode("utf-8")


class FakeHttp:
    """Replays queued `(status, bytes)` answers and records every request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, url, headers, body, timeout):
        self.requests.append({"url": url, "headers": dict(headers),
                              "body": json.loads(body), "timeout": timeout})
        if not self.answers:
            raise AssertionError("the fake HTTP caller ran out of answers")
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    @property
    def calls(self):
        return len(self.requests)


def deep(obj):
    return copy.deepcopy(obj)
