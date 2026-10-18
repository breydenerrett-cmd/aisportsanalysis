"""A tiny, fully synthetic world for the hounds tests.

Nothing here reads a live ledger. ``make_world(root)`` writes, under ``root``:

  evidence/decisions_v2.jsonl      frozen decisions (plays and one refusal)
  evidence/paper_wagers_v2.jsonl   the wagers taken from them
  data/paper_accounts/<sys>.jsonl  graded settlements per engine system
  data/processed/odds_multibook.jsonl   captured boards (3 instants per game)
  config/house_hounds.json         alpha + bravo (engine) + delta (benched)
  config/house_pack.json           charlie (a pack hound)
  evidence/hounds_house_v1.jsonl   charlie's bets (forward + one replay row)
  evidence/hounds_user_v1.jsonl    a user hound definition and one bet

and returns ``Sources`` pointing at it. The numbers are chosen so each
expectation can be checked by hand (see the comments at the call sites).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.board import ids
from src.hounds.ledgers import Sources

START = "2026-10-01T23:00:00Z"
DECIDE = "2026-10-01T15:00:00+00:00"
BOARD_T0 = "2026-10-01T14:50:00+00:00"      # the board the decision read
BOARD_T1 = "2026-10-01T20:00:00+00:00"
CLOSE_T = "2026-10-01T22:30:00+00:00"       # last capture before first pitch
BOOKS = ("bk1", "bk2", "bk3", "bk4", "bk5", "bk6")


def sel(market, side, line=None):
    return ids.selection_id(sport="mlb", market_key=market, side=side, line=line)


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def h2h_rows(event, observed, home_prices, away_prices, start=START):
    return [{"observed_utc": observed, "event_id": event, "commence_time": start,
             "home_team": f"Home {event}", "away_team": f"Away {event}",
             "book": b, "book_last_update": observed,
             "home_price": h, "away_price": a}
            for b, h, a in zip(BOOKS, home_prices, away_prices)]


def totals_rows(event, observed, total, over, under, start=START):
    return [{"observed_utc": observed, "event_id": event, "commence_time": start,
             "home_team": f"Home {event}", "away_team": f"Away {event}",
             "market": "totals", "book": b, "book_last_update": observed,
             "total": total, "over_price": o, "under_price": u}
            for b, o, u in zip(BOOKS, over, under)]


def decision(system, event, market, side, line, price, book, utc=DECIDE,
             verdict="play", provenance="live_pre_commencement",
             p_prov="placeholder", fair=0.54):
    return {"event_id": event, "system_id": system, "market_key": market,
            "selection_id": sel(market, side, line), "line": line,
            "decision_utc": utc, "verdict": verdict, "price_american": price,
            "book": book, "consensus_fair": fair, "p_model_provenance": p_prov,
            "record_provenance": provenance, "books_at_decision": 6,
            "friction": {"book_count": 6, "dispersion": 0.05, "vig": 0.04},
            "refusal_reason": None if verdict == "play" else "thin_board",
            "thesis": f"{system} thesis for {event}. Second sentence.",
            "stake_units": 1.0}


def wager(bet_id, system, event, market, side, line, price, utc=DECIDE, date="2026-10-01"):
    return {"bet_id": bet_id, "date": date, "decision_utc": utc, "event_id": event,
            "game_pk": None, "label": "PAPER", "line": line, "market_key": market,
            "price_american": price, "selection_id": sel(market, side, line),
            "settlement_rule": market, "side": side, "stake_units": 1.0,
            "system_id": system}


def account(bet_id, system, day, outcome, profit, market, side, line, price):
    return {"bet_id": bet_id, "day": day, "outcome": outcome, "profit_units": profit,
            "market_key": market, "side": side, "line": line,
            "price_american": price, "system_id": system, "label": "PAPER",
            "stake_units": 1.0, "selection_id": sel(market, side, line)}


def make_world(root: Path) -> Sources:
    root = Path(root)
    odds = []
    # E1: h2h. Decision board T0 home prices -120 -125 -130 -118 -122 -126 (mean
    # decimal 1.8106 -> -123). Closing board: all six books home -135 / away +115.
    odds += h2h_rows("E1", BOARD_T0, (-120, -125, -130, -118, -122, -126),
                     (100, 105, 115, 101, 102, 106))
    odds += h2h_rows("E1", BOARD_T1, (-128,) * 6, (108,) * 6)
    odds += h2h_rows("E1", CLOSE_T, (-135,) * 6, (115,) * 6)
    # E2: h2h; the recorded away price +112 is NOT on the T0 board (best is +110).
    away_t0 = (100, 104, 108, 110, 102, 106)
    odds += h2h_rows("E2", BOARD_T0, (-120,) * 6, away_t0)
    odds += h2h_rows("E2", CLOSE_T, (-150,) * 6, (130,) * 6)
    # E3: h2h, ungraded at the time of the snapshot.
    odds += h2h_rows("E3", BOARD_T0, (-110,) * 6, (-110,) * 6)
    odds += h2h_rows("E3", CLOSE_T, (-110,) * 6, (-110,) * 6)
    # E4: totals 8.5, under bet, closing price shortens the under.
    odds += totals_rows("E4", BOARD_T0, "8.5", (-105,) * 6, (-115, -110, -115, -110, -112, -113))
    odds += totals_rows("E4", CLOSE_T, "8.5", (100,) * 6, (-120,) * 6)
    # E5: the replay bet's game.
    odds += h2h_rows("E5", BOARD_T0, (-110,) * 6, (-110,) * 6)
    odds += h2h_rows("E5", CLOSE_T, (-110,) * 6, (-110,) * 6)
    # E6 (pack hound's forward bet): same shape as E1's closing.
    odds += h2h_rows("E6", BOARD_T0, (110,) * 6, (-130,) * 6)
    odds += h2h_rows("E6", CLOSE_T, (120,) * 6, (-140,) * 6)
    write_jsonl(root / "data/processed/odds_multibook.jsonl", odds)

    decisions = [
        decision("sys_a", "E1", "h2h", "home", None, -118, "bk4"),
        decision("sys_a", "E2", "h2h", "away", None, 112, "bk4"),
        decision("sys_a", "E3", "h2h", "home", None, -110, "bk1"),
        decision("sys_a", "E4", "totals", "under", "8.5", -110, "bk2"),
        decision("sys_a", "E5", "h2h", "home", None, -110, "bk1",
                 utc="2026-10-02T16:00:00+00:00", provenance="replay"),
        decision("sys_a", "E7", "h2h", "home", None, None, None,
                 utc="2026-10-02T16:00:00+00:00", verdict="refused_thin"),
        decision("sys_b", "E1", "h2h", "away", None, 115, "bk3", p_prov="model_derived"),
        decision("sys_d", "E8", "h2h", "home", None, -105, "bk1",
                 utc="2026-09-20T15:00:00+00:00"),
    ]
    write_jsonl(root / "evidence/decisions_v2.jsonl", decisions)
    wagers = [
        wager("w1", "sys_a", "E1", "h2h", "home", None, -118),
        wager("w2", "sys_a", "E2", "h2h", "away", None, 112),
        wager("w3", "sys_a", "E3", "h2h", "home", None, -110),
        wager("w4", "sys_a", "E4", "totals", "under", "8.5", -110),
        wager("w5", "sys_a", "E5", "h2h", "home", None, -110,
              utc="2026-10-02T16:00:00+00:00", date="2026-10-02"),
        wager("w6", "sys_b", "E1", "h2h", "away", None, 115),
        wager("w7", "sys_d", "E8", "h2h", "home", None, -105,
              utc="2026-09-20T15:00:00+00:00", date="2026-09-20"),
    ]
    write_jsonl(root / "evidence/paper_wagers_v2.jsonl", wagers)
    write_jsonl(root / "data/paper_accounts/sys_a.jsonl", [
        account("w1", "sys_a", "2026-10-01", "win", 0.8475, "h2h", "home", None, -118),
        account("w2", "sys_a", "2026-10-01", "loss", -1.0, "h2h", "away", None, 112),
        account("w4", "sys_a", "2026-10-01", "push", 0.0, "totals", "under", "8.5", -110),
        account("w5", "sys_a", "2026-10-02", "loss", -1.0, "h2h", "home", None, -110),
    ])
    write_jsonl(root / "data/paper_accounts/sys_b.jsonl", [
        account("w6", "sys_b", "2026-10-01", "void", 0.0, "h2h", "away", None, 115)])
    write_jsonl(root / "data/paper_accounts/sys_d.jsonl", [
        account("w7", "sys_d", "2026-09-20", "win", 0.9524, "h2h", "home", None, -105)])

    cfg = {"hounds": [
        {"id": "alpha", "name": "Alpha", "tagline": "first", "kind": "house",
         "category": "stats", "style": "test", "system_id": "sys_a",
         "markets": ["h2h", "totals"], "rule_text": "Alpha rule."},
        {"id": "bravo", "name": "Bravo", "tagline": "second", "kind": "baseline",
         "category": "baseline", "style": "test", "system_id": "sys_b",
         "rule_text": "Bravo rule."},
        {"id": "delta", "name": "Delta", "tagline": "quiet", "kind": "house",
         "category": "market", "style": "test", "system_id": "sys_d",
         "rule_text": "Delta rule."}]}
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config/house_hounds.json").write_text(json.dumps(cfg), encoding="utf-8")
    (root / "config/house_pack.json").write_text(json.dumps({"hounds": [
        {"id": "charlie", "name": "Charlie", "tagline": "pack", "category": "math",
         "style": "pack test", "rule_text": "Charlie rule.", "sports": ["mlb"],
         "markets": ["h2h"]}]}), encoding="utf-8")

    pack_rows = [
        {"hound_id": "charlie", "date": "2026-10-01", "event_id": "E6", "sport": "mlb",
         "market": "h2h", "selection": "home", "line": None, "price_average": 110,
         "price_best": 112, "book_count": 6, "lock_utc": DECIDE, "start_utc": START,
         "reason": "pack reason", "who_decided": "rule", "segment": "forward",
         "bet_id": "p1", "book": "bk2"},
        {"hound_id": "charlie", "bet_id": "p1", "result": "win", "units": 1.12},
        {"hound_id": "charlie", "date": "2026-09-28", "event_id": "E9", "sport": "mlb",
         "market": "h2h", "selection": "away", "price_average": -105, "price_best": -102,
         "lock_utc": "2026-09-28T15:00:00+00:00", "start_utc": "2026-09-28T23:00:00Z",
         "reason": "replayed", "who_decided": "rule", "segment": "replay",
         "bet_id": "p2", "result": "loss", "units": -1.0},
    ]
    write_jsonl(root / "evidence/hounds_house_v1.jsonl", pack_rows)
    user_rows = [
        {"kind": "hound", "hound_id": "u-1", "name": "Rover", "owner_display": "pat",
         "rule_text": "Pat's rule.", "category": "mixed", "style": "mine"},
        {"hound_id": "u-1", "date": "2026-10-01", "event_id": "E1", "sport": "mlb",
         "market": "moneyline", "selection": "away", "price_best": 115,
         "price_average": 108, "lock_utc": DECIDE, "start_utc": START,
         "segment": "forward", "bet_id": "q1", "who_decided": "rule",
         "result": "loss", "units": -1.0},
    ]
    write_jsonl(root / "evidence/hounds_user_v1.jsonl", user_rows)

    return Sources(
        decisions=root / "evidence/decisions_v2.jsonl",
        wagers=root / "evidence/paper_wagers_v2.jsonl",
        accounts_dir=root / "data/paper_accounts",
        multibook=root / "data/processed/odds_multibook.jsonl",
        card_v2=root / "evidence/cards_v2_absent.jsonl",
        house_hounds_cfg=root / "config/house_hounds.json",
        house_pack_cfg=root / "config/house_pack.json",
        pack_ledgers=(("house", root / "evidence/hounds_house_v1.jsonl"),
                      ("user", root / "evidence/hounds_user_v1.jsonl")))
