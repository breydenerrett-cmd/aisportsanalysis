"""MLB_VALUE_SHADOW_V1 (src/analysis/mlb_value_shadow.py).

Each test pins one rule of docs/PREREG_MLB_VALUE_SHADOW_V1.md. Every store
the module reads or writes is a temp file injected by path: nothing here
touches data/ or evidence/, and the isolation tests prove the real card and
engine stores are byte-for-byte unchanged afterwards.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.analysis import lobo_value as lobo
from src.analysis import mlb_value_shadow as shadow
from src.core import odds as odds_math
from src.ledger.chain import HashChainLedger

ROOT = Path(__file__).resolve().parent.parent

NOW = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)   # 16:00 ET
DATE = "2026-09-21"
FIRST_PITCH = NOW + timedelta(hours=2)                     # 18:00 ET
EVENT, GAME_PK = "evA", "900001"
EVENT2, GAME_PK2 = "evB", "900002"
HOME, AWAY = "Seattle Mariners", "Athletics"


def _z(moment):
    return moment.isoformat().replace("+00:00", "Z")


def _prop(book, player, over, under, *, line="1.5", market="batter_total_bases",
          minutes_ago=5.0, now=NOW, event=EVENT, first_pitch=FIRST_PITCH, sides=("Over", "Under")):
    stamp = _z(now - timedelta(minutes=minutes_ago))
    rows = []
    for side, price in (("Over", over), ("Under", under)):
        if side not in sides:
            continue
        rows.append({
            "event_id": event, "game_date": DATE, "commence_time": _z(first_pitch),
            "home_team": HOME, "away_team": AWAY, "market": market,
            "selection": f"{player}:{side}", "player": player, "side": side,
            "line": line, "price": price, "book": book, "book_last_update": stamp,
            "observed_utc": stamp, "capture_phase": "gate",
        })
    return rows


def _board(player, n_others, *, soft=("soft", 110, -130), fair=(-110, -110), **kw):
    rows = []
    for i in range(n_others):
        rows += _prop(f"book{i}", player, fair[0], fair[1], **kw)
    if soft is not None:
        rows += _prop(soft[0], player, soft[1], soft[2], **kw)
    return rows


def _spread(book, home_line, home_price, away_price, *, minutes_ago=5.0, now=NOW,
            event=EVENT, first_pitch=FIRST_PITCH, sport=None):
    stamp = now - timedelta(minutes=minutes_ago)
    row = {"observed_utc": stamp.isoformat(), "event_id": event,
           "commence_time": _z(first_pitch), "home_team": HOME, "away_team": AWAY,
           "market": "spreads", "book": book, "book_last_update": _z(stamp),
           "home_line": str(home_line), "home_price": home_price,
           "away_line": str(-float(home_line)), "away_price": away_price}
    if sport:
        row["sport"] = sport
    return row


def _total(book, total, over, under, *, minutes_ago=5.0, now=NOW, event=EVENT,
           first_pitch=FIRST_PITCH):
    stamp = now - timedelta(minutes=minutes_ago)
    return {"observed_utc": stamp.isoformat(), "event_id": event,
            "commence_time": _z(first_pitch), "home_team": HOME, "away_team": AWAY,
            "market": "totals", "book": book, "book_last_update": _z(stamp),
            "total": str(total), "over_price": over, "under_price": under}


def _map_row(event, game_pk, *, ambiguous=False):
    return {"event_id": event, "game_pk": game_pk, "resolved": game_pk is not None,
            "ambiguous": ambiguous, "candidates": [], "reason": None,
            "source": "mlb_schedule", "commence_time": _z(FIRST_PITCH)}


def _batter(game_pk, name, *, player_id=1, pa=4, h=1, total_bases=1):
    return {"type": "batter", "date": DATE, "game_pk": int(game_pk), "player_id": player_id,
            "player_name": name, "side": "home", "team_id": 136, "team_name": HOME,
            "pa": pa, "ab": pa, "h": h, "doubles": 0, "triples": 0, "hr": 0, "r": 0,
            "rbi": 0, "bb": 0, "k": 0, "sb": 0, "total_bases": total_bases,
            "hits_runs_rbi": h, "observed_utc": "2026-09-22T10:10:00Z"}


def _linescore(game_pk, away_runs, home_runs, *, innings_played=9):
    innings = [{"num": 1, "away_runs": away_runs, "home_runs": home_runs}]
    innings += [{"num": n, "away_runs": 0, "home_runs": 0}
                for n in range(2, innings_played + 1)]
    return {"type": "linescore", "game_pk": int(game_pk), "date": DATE, "innings": innings,
            "first_inning_away_runs": away_runs, "first_inning_home_runs": home_runs,
            "first_inning_scored": bool(away_runs or home_runs), "first_team_to_score": None,
            "observed_utc": "2026-09-22T10:10:00Z"}


def _write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


class Stores:
    """Temp stores for one test, injected by path."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.props = self.tmp / "batter_props.jsonl"
        self.multibook = self.tmp / "odds_multibook.jsonl"
        self.map = self.tmp / "event_game_map.jsonl"
        self.box = self.tmp / "boxscores_2026.jsonl"
        self.results = self.tmp / "mlb_results.csv"
        self.ledger = self.tmp / "ledger"
        _write_jsonl(self.map, [_map_row(EVENT, GAME_PK), _map_row(EVENT2, GAME_PK2)])
        _write_jsonl(self.props, [])
        _write_jsonl(self.multibook, [])

    def set_props(self, rows):
        _write_jsonl(self.props, rows)

    def set_lines(self, rows):
        _write_jsonl(self.multibook, rows)

    def set_map(self, rows):
        _write_jsonl(self.map, rows)

    def set_box(self, rows):
        _write_jsonl(self.box, rows)

    def set_results(self, rows):
        with open(self.results, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["game_pk", "date", "away_score", "home_score"])
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def publish(self, *, now=NOW, arms=None, dry_run=False, date=DATE):
        return shadow.publish(date, now=now, dry_run=dry_run, ledger_dir=self.ledger,
                              arms=arms, props_path=self.props,
                              multibook_path=self.multibook, map_path=self.map)

    def settle(self, *, now, dry_run=False):
        return shadow.settle_recent(now=now, ledger_dir=self.ledger, dry_run=dry_run,
                                    box_paths={"2026": self.box},
                                    results_path=self.results)

    def decisions(self, arm_name):
        arm = shadow.ARMS_BY_NAME[arm_name]
        return [r for r in HashChainLedger(shadow.decisions_path(self.ledger, arm)).read()
                if r.get("kind") == "decision"]

    def settled(self, arm_name):
        arm = shadow.ARMS_BY_NAME[arm_name]
        return HashChainLedger(shadow.settled_path(self.ledger, arm)).read()

    def scans(self, arm_name):
        arm = shadow.ARMS_BY_NAME[arm_name]
        return HashChainLedger(shadow.scans_path(self.ledger, arm)).read()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.s = Stores(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# The value rule, as the arms apply it
# ---------------------------------------------------------------------------

class PriceRules(Base):
    def test_a_price_better_than_five_other_books_locks_a_total_bases_decision(self):
        self.s.set_props(_board("Cal Raleigh", 5))
        out = self.s.publish(arms=["A_TOTAL_BASES"])
        rows = self.s.decisions("A_TOTAL_BASES")
        self.assertEqual(len(rows), 1)
        d = rows[0]
        self.assertEqual((d["player"], d["side"], d["line"], d["price"], d["book"]),
                         ("Cal Raleigh", "over", 1.5, 110, "soft"))
        self.assertAlmostEqual(d["ev"], 0.5 * 2.10 - 1.0, places=9)
        self.assertEqual(d["game_pk"], GAME_PK)
        self.assertFalse(d["customer_surface"])
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["new_decisions"], 1)

    def test_the_judged_book_is_never_in_its_own_consensus(self):
        self.s.set_props(_board("Cal Raleigh", 5))
        self.s.publish(arms=["A_TOTAL_BASES"])
        d = self.s.decisions("A_TOTAL_BASES")[0]
        # Five symmetric -110/-110 books de-vig to exactly 50%.
        self.assertAlmostEqual(d["fair_probability"], 0.5, places=12)
        self.assertEqual(d["n_other_books"], 5)
        self.assertNotIn("soft", d["other_books"])

    def test_minus_200_is_never_taken_and_minus_199_is(self):
        # Every other book: Under a 75% shot (-300/+300 de-vigs to it).
        refused = _board("Cal Raleigh", 5, fair=(300, -300), soft=("soft", 150, -200))
        self.s.set_props(refused)
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertFalse([d for d in self.s.decisions("A_TOTAL_BASES") if d["side"] == "under"])

        allowed = _board("Julio Rodriguez", 5, fair=(300, -300), soft=("soft", 150, -199))
        self.s.set_props(refused + allowed)
        self.s.publish(arms=["A_TOTAL_BASES"])
        unders = [d for d in self.s.decisions("A_TOTAL_BASES") if d["side"] == "under"]
        self.assertEqual([(d["player"], d["price"]) for d in unders], [("Julio Rodriguez", -199)])

    def test_a_price_under_two_percent_better_is_not_value(self):
        # +102 against a fair 50%: EV 1.0% under every method.
        self.s.set_props(_board("Cal Raleigh", 5, soft=("soft", 102, -125)))
        out = self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["candidates"], 0)
        self.assertGreater(out["A_TOTAL_BASES"]["counts"]["lines_judged"], 0)

    def test_total_bases_needs_five_other_books(self):
        self.s.set_props(_board("Cal Raleigh", 4))
        out = self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["lines_judged"], 0)
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["boards_judged"], 1)

    def test_hits_needs_two_other_books_and_is_labelled_thin(self):
        one = _board("Cal Raleigh", 1, market="batter_hits", line="0.5")
        self.s.set_props(one)
        self.s.publish(arms=["B_HITS"])
        self.assertEqual(self.s.decisions("B_HITS"), [])
        two = _board("Cal Raleigh", 2, market="batter_hits", line="0.5")
        self.s.set_props(two)
        self.s.publish(arms=["B_HITS"])
        rows = self.s.decisions("B_HITS")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], shadow.LABEL_THIN)
        self.assertEqual(rows[0]["n_other_books"], 2)

    def test_a_stale_book_is_neither_judged_nor_in_the_consensus(self):
        rows = _board("Cal Raleigh", 5, soft=None)
        rows += _prop("asleep", "Cal Raleigh", 130, -160, minutes_ago=45)
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])
        # ...and a sleeping book cannot make up the numbers for someone else.
        rows = _board("Cal Raleigh", 4)
        rows += _prop("asleep", "Cal Raleigh", -110, -110, minutes_ago=45)
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])

    def test_a_board_older_than_an_hour_is_never_judged(self):
        self.s.set_props(_board("Cal Raleigh", 5, minutes_ago=61))
        out = self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["boards_stale"], 1)
        self.s.set_props(_board("Cal Raleigh", 5, minutes_ago=59))
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(len(self.s.decisions("A_TOTAL_BASES")), 1)

    def test_a_long_shot_clearing_only_under_proportional_is_refused(self):
        def ev(fav, dog, price):
            out = {}
            for m in lobo.DEVIG_METHODS:
                _, fair = odds_math.devig_two_way(fav, dog, method=m)
                out[m] = fair * odds_math.american_to_decimal(price) - 1.0
            return out

        refused = ev(-320, 260, 290)
        self.assertGreaterEqual(refused["proportional"], shadow.MIN_EV)
        self.assertLess(min(refused.values()), shadow.MIN_EV)
        self.s.set_props(_board("Cal Raleigh", 5, fair=(-320, 260), soft=("soft", -400, 290)))
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])

        cleared = ev(-320, 260, 310)
        self.assertGreaterEqual(min(cleared.values()), shadow.MIN_EV)
        self.s.set_props(_board("Cal Raleigh", 5, fair=(-320, 260), soft=("soft", -400, 310)))
        self.s.publish(arms=["A_TOTAL_BASES"])
        d = self.s.decisions("A_TOTAL_BASES")[0]
        self.assertAlmostEqual(d["ev"], min(cleared.values()), places=12)
        self.assertEqual(d["ev"], min(d["ev_by_method"].values()))
        self.assertEqual(d["devig_method"], min(cleared, key=cleared.get))


class PropQuotes(Base):
    def test_a_one_sided_book_is_never_judged_and_never_in_a_consensus(self):
        # betrivers quotes Over only.
        rows = _board("Cal Raleigh", 4, soft=None)
        rows += _prop("betrivers", "Cal Raleigh", 200, None, sides=("Over",))
        rows += _prop("soft", "Cal Raleigh", 110, -130)
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])   # 4 two-way others only

        rows = _board("Cal Raleigh", 5, soft=None)
        rows += _prop("betrivers", "Cal Raleigh", 200, None, sides=("Over",))
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])   # +200 one-sided never judged

    def test_only_each_books_newest_observation_counts(self):
        rows = _board("Cal Raleigh", 5, soft=None)
        rows += _prop("soft", "Cal Raleigh", 110, -130, minutes_ago=10)
        rows += _prop("soft", "Cal Raleigh", -110, -110, minutes_ago=2)
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])

    def test_a_player_the_book_dropped_is_not_quoted_from_an_older_observation(self):
        rows = _board("Cal Raleigh", 5, soft=None)
        rows += _prop("soft", "Cal Raleigh", 110, -130, minutes_ago=10)
        rows += _prop("soft", "Julio Rodriguez", -110, -110, minutes_ago=2)
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])

    def test_books_are_compared_only_at_the_same_line(self):
        rows = _board("Cal Raleigh", 5, soft=None, line="1.5")
        rows += _prop("soft", "Cal Raleigh", 110, -130, line="0.5")
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])

    def test_player_spelling_differences_across_books_join(self):
        rows = []
        for i, name in enumerate(["José Ramírez", "Jose Ramirez", "Jose Ramirez",
                                  "José Ramírez", "Jose Ramirez"]):
            rows += _prop(f"book{i}", name, -110, -110)
        rows += _prop("soft", "Jose Ramirez", 110, -130)
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        rows = self.s.decisions("A_TOTAL_BASES")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player_norm"], "jose ramirez")


class LockAndHold(Base):
    def test_one_decision_per_player_held_across_later_runs_whatever_moves(self):
        self.s.set_props(_board("Cal Raleigh", 5))
        self.s.publish(arms=["A_TOTAL_BASES"])
        later = NOW + timedelta(minutes=30)
        moved = _board("Cal Raleigh", 5, soft=("soft", 150, -190), line="0.5", now=later)
        self.s.set_props(_board("Cal Raleigh", 5) + moved)
        out = self.s.publish(arms=["A_TOTAL_BASES"], now=later)
        rows = self.s.decisions("A_TOTAL_BASES")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["line"], rows[0]["price"]), (1.5, 110))
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["held"], 1)

    def test_the_best_ev_candidate_is_the_one_locked_for_a_key(self):
        rows = _board("Cal Raleigh", 5, soft=("soft", 110, -130))
        rows += _prop("softer", "Cal Raleigh", 125, -150)
        self.s.set_props(rows)
        self.s.publish(arms=["A_TOTAL_BASES"])
        rows = self.s.decisions("A_TOTAL_BASES")
        self.assertEqual([(d["book"], d["price"]) for d in rows], [("softer", 125)])

    def test_nothing_is_decided_outside_the_four_hour_window(self):
        early = FIRST_PITCH - timedelta(hours=4, minutes=5)
        self.s.set_props(_board("Cal Raleigh", 5, now=early))
        out = self.s.publish(arms=["A_TOTAL_BASES"], now=early)
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["boards_outside_window"], 1)
        inside = FIRST_PITCH - timedelta(hours=3, minutes=55)
        self.s.set_props(_board("Cal Raleigh", 5, now=inside))
        self.s.publish(arms=["A_TOTAL_BASES"], now=inside)
        self.assertEqual(len(self.s.decisions("A_TOTAL_BASES")), 1)

    def test_nothing_is_decided_at_or_after_first_pitch(self):
        for when in (FIRST_PITCH, FIRST_PITCH + timedelta(minutes=10)):
            self.s.set_props(_board("Cal Raleigh", 5, now=when, minutes_ago=1))
            self.s.publish(arms=["A_TOTAL_BASES"], now=when)
            self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])

    def test_rows_observed_after_now_are_invisible(self):
        self.s.set_props(_board("Cal Raleigh", 5, now=NOW + timedelta(minutes=20)))
        self.s.publish(arms=["A_TOTAL_BASES"], now=NOW)
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])

    def test_the_date_cap_counts_overflow_and_never_exceeds(self):
        rows = []
        for i in range(shadow.MAX_PER_DATE + 2):
            rows += _board(f"Player {i:02d}", 5, soft=("soft", 110 + i, -130))
        self.s.set_props(rows)
        out = self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(len(self.s.decisions("A_TOTAL_BASES")), shadow.MAX_PER_DATE)
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["capped"], 2)
        # Highest EV first: the two cheapest prices are the ones left out.
        prices = sorted(d["price"] for d in self.s.decisions("A_TOTAL_BASES"))
        self.assertEqual(prices[0], 112)
        out = self.s.publish(arms=["A_TOTAL_BASES"], now=NOW + timedelta(minutes=1))
        self.assertEqual(len(self.s.decisions("A_TOTAL_BASES")), shadow.MAX_PER_DATE)
        self.assertEqual(out["A_TOTAL_BASES"]["counts"]["capped"], 2)

    def test_unmapped_and_ambiguous_games_are_skipped_and_counted(self):
        self.s.set_map([_map_row(EVENT, None), _map_row(EVENT2, GAME_PK2, ambiguous=True)])
        rows = _board("Cal Raleigh", 5) + _board("Mookie Betts", 5, event=EVENT2)
        self.s.set_props(rows)
        out = self.s.publish(arms=["A_TOTAL_BASES"])
        self.assertEqual(self.s.decisions("A_TOTAL_BASES"), [])
        c = out["A_TOTAL_BASES"]["counts"]
        self.assertEqual((c["skipped_unmapped"], c["skipped_ambiguous"]), (1, 1))

    def test_dry_run_writes_nothing(self):
        self.s.set_props(_board("Cal Raleigh", 5))
        out = self.s.publish(arms=["A_TOTAL_BASES"], dry_run=True)
        self.assertEqual(len(out["A_TOTAL_BASES"]["decisions"]), 1)
        self.assertFalse(self.s.ledger.exists())

    def test_an_unchanged_rerun_appends_no_scan_row(self):
        self.s.set_props(_board("Cal Raleigh", 4))
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.s.publish(arms=["A_TOTAL_BASES"], now=NOW + timedelta(minutes=1))
        self.assertEqual(len(self.s.scans("A_TOTAL_BASES")), 1)

    def test_every_chain_verifies(self):
        self.s.set_props(_board("Cal Raleigh", 5))
        self.s.publish()
        for name, v in shadow.verify(ledger_dir=self.s.ledger).items():
            self.assertTrue(v["ok"], (name, v))


class GameLines(Base):
    def test_run_line_value_is_judged_on_the_same_number_only(self):
        rows = [_spread(f"book{i}", -1.5, 130, -150) for i in range(5)]
        rows.append(_spread("soft", -1.5, 150, -175))
        rows.append(_spread("lonely", -2.5, 260, -330))
        self.s.set_lines(rows)
        self.s.publish(arms=["C_RUN_LINE"])
        rows = self.s.decisions("C_RUN_LINE")
        self.assertEqual(len(rows), 1)
        d = rows[0]
        self.assertEqual((d["side"], d["line"], d["price"], d["book"]), ("home", -1.5, 150, "soft"))
        self.assertEqual(d["decision_key"], f"C_RUN_LINE|{GAME_PK}")

    def test_nfl_rows_in_the_same_store_are_ignored(self):
        rows = [_spread(f"book{i}", -1.5, 130, -150, sport="nfl") for i in range(5)]
        rows.append(_spread("soft", -1.5, 150, -175, sport="nfl"))
        self.s.set_lines(rows)
        self.s.publish(arms=["C_RUN_LINE"])
        self.assertEqual(self.s.decisions("C_RUN_LINE"), [])

    def test_game_total_value(self):
        rows = [_total(f"book{i}", 8.5, -110, -110) for i in range(5)]
        rows.append(_total("soft", 8.5, 110, -130))
        self.s.set_lines(rows)
        self.s.publish(arms=["D_GAME_TOTAL"])
        d = self.s.decisions("D_GAME_TOTAL")[0]
        self.assertEqual((d["side"], d["line"], d["price"]), ("over", 8.5, 110))

    def test_each_arm_writes_only_its_own_ledger(self):
        rows = [_spread(f"book{i}", -1.5, 130, -150) for i in range(5)]
        rows.append(_spread("soft", -1.5, 150, -175))
        self.s.set_lines(rows)
        self.s.publish()
        self.assertEqual(len(self.s.decisions("C_RUN_LINE")), 1)
        for other in ("A_TOTAL_BASES", "B_HITS", "D_GAME_TOTAL"):
            self.assertEqual(self.s.decisions(other), [])


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

class PropGrading(Base):
    def _lock(self, player="Jose Ramirez", market="batter_total_bases", line="1.5",
              soft=("soft", 110, -130)):
        arm = "A_TOTAL_BASES" if market == "batter_total_bases" else "B_HITS"
        n = 5 if arm == "A_TOTAL_BASES" else 2
        self.s.set_props(_board(player, n, soft=soft, market=market, line=line))
        self.s.publish(arms=[arm])
        self.assertEqual(len(self.s.decisions(arm)), 1)
        return arm

    def test_accented_box_name_grades_an_unaccented_prop(self):
        arm = self._lock("Jose Ramirez")
        self.s.set_box([_batter(GAME_PK, "José Ramírez", total_bases=2), _linescore(GAME_PK, 1, 3)])
        counts = self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(counts[arm]["graded"], 1)
        s = self.s.settled(arm)[0]
        self.assertEqual((s["result"], s["stat_value"]), ("WIN", 2))
        self.assertAlmostEqual(s["profit_units"], 1.10, places=4)

    def test_suffix_and_parenthesis_names_grade(self):
        for prop_name, box_name in (("Bobby Witt Jr.", "Bobby Witt"),
                                    ("Max Muncy", "Max Muncy (2002)"),
                                    ("Ha-Seong Kim", "Ha Seong Kim")):
            with self.subTest(prop=prop_name), tempfile.TemporaryDirectory() as tmp:
                self.s = Stores(tmp)
                arm = self._lock(prop_name)
                self.s.set_box([_batter(GAME_PK, box_name, total_bases=0),
                                _linescore(GAME_PK, 1, 3)])
                self.s.settle(now=NOW + timedelta(days=1))
                s = self.s.settled(arm)[0]
                self.assertEqual(s["result"], "LOSS")
                self.assertEqual(s["profit_units"], -1.0)

    def test_hits_grade_on_the_hits_stat(self):
        arm = self._lock(market="batter_hits", line="0.5", soft=("soft", 110, -130))
        self.s.set_box([_batter(GAME_PK, "Jose Ramirez", h=0, total_bases=0),
                        _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(self.s.settled(arm)[0]["result"], "LOSS")

    def test_a_player_with_no_box_row_is_void_did_not_bat(self):
        arm = self._lock()
        self.s.set_box([_batter(GAME_PK, "Someone Else"), _linescore(GAME_PK, 1, 3)])
        counts = self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(counts[arm]["voids"], 1)
        s = self.s.settled(arm)[0]
        self.assertEqual((s["result"], s["reason"], s["profit_units"]), ("VOID", "did not bat", 0.0))

    def test_zero_plate_appearances_is_void_did_not_bat(self):
        arm = self._lock()
        self.s.set_box([_batter(GAME_PK, "Jose Ramirez", pa=0, h=0, total_bases=0),
                        _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(self.s.settled(arm)[0]["reason"], "did not bat")

    def test_two_players_with_one_normalised_name_is_void(self):
        arm = self._lock()
        self.s.set_box([_batter(GAME_PK, "José Ramírez", player_id=1),
                        _batter(GAME_PK, "Jose Ramirez", player_id=2),
                        _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(self.s.settled(arm)[0]["reason"], "ambiguous name")

    def test_a_reingested_duplicate_row_is_not_ambiguous(self):
        arm = self._lock()
        row = _batter(GAME_PK, "José Ramírez", total_bases=3)
        self.s.set_box([row, dict(row), _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(self.s.settled(arm)[0]["result"], "WIN")

    def test_no_final_stays_pending_then_voids_after_seven_days(self):
        arm = self._lock()
        self.s.set_box([_batter(GAME_PK, "Jose Ramirez")])   # no linescore: not final
        counts = self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(counts[arm], {"graded": 0, "voids": 0, "unsettled": 1, "mismatches": 0})
        self.assertEqual(self.s.settled(arm), [])
        self.s.settle(now=NOW + timedelta(days=6))
        self.assertEqual(self.s.settled(arm), [])
        counts = self.s.settle(now=NOW + timedelta(days=7))
        self.assertEqual(counts[arm]["voids"], 1)
        self.assertEqual((self.s.settled(arm)[0]["result"], self.s.settled(arm)[0]["reason"]),
                         ("VOID", "no final"))
        # Settled once: a later run never grades it again.
        self.s.set_box([_batter(GAME_PK, "Jose Ramirez"), _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=8))
        self.assertEqual(len(self.s.settled(arm)), 1)

    def test_two_different_linescores_hold_the_grade_then_void(self):
        arm = self._lock()
        self.s.set_box([_batter(GAME_PK, "Jose Ramirez", total_bases=2),
                        _linescore(GAME_PK, 1, 3), _linescore(GAME_PK, 2, 3)])
        counts = self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual((counts[arm]["unsettled"], counts[arm]["mismatches"]), (1, 1))
        self.assertEqual(self.s.settled(arm), [])
        self.s.settle(now=NOW + timedelta(days=7))
        self.assertEqual(self.s.settled(arm)[0]["reason"], "box-score linescores disagree")

    def test_a_late_final_grades_by_game_pk_whatever_its_date(self):
        arm = self._lock()
        line = _linescore(GAME_PK, 1, 3)
        line["date"] = "2026-09-23"                           # suspended, finished later
        batter = _batter(GAME_PK, "Jose Ramirez", total_bases=2)
        batter["date"] = "2026-09-23"
        self.s.set_box([batter, line])
        self.s.settle(now=NOW + timedelta(days=3))
        self.assertEqual(self.s.settled(arm)[0]["result"], "WIN")

    def test_settle_dry_run_writes_nothing(self):
        arm = self._lock()
        self.s.set_box([_batter(GAME_PK, "Jose Ramirez", total_bases=2), _linescore(GAME_PK, 1, 3)])
        counts = self.s.settle(now=NOW + timedelta(days=1), dry_run=True)
        self.assertEqual(counts[arm]["graded"], 1)
        self.assertEqual(self.s.settled(arm), [])


class GameLineGrading(Base):
    def _lock_run_line(self, side_price_home, side_price_away, soft_home, soft_away, line=-1.5):
        rows = [_spread(f"book{i}", line, side_price_home, side_price_away) for i in range(5)]
        rows.append(_spread("soft", line, soft_home, soft_away))
        self.s.set_lines(rows)
        self.s.publish(arms=["C_RUN_LINE"])
        return self.s.decisions("C_RUN_LINE")[0]

    def test_home_minus_one_and_a_half(self):
        d = self._lock_run_line(130, -150, 150, -175)
        self.assertEqual((d["side"], d["line"]), ("home", -1.5))
        for (away, home), result in (((1, 3), "WIN"), ((2, 3), "LOSS"), ((4, 3), "LOSS")):
            with self.subTest(score=(away, home)):
                d_arm = shadow.ARMS_BY_NAME["C_RUN_LINE"]
                box = shadow.BoxIndex(batters={}, finals={GAME_PK: {(away, home, 9)}})
                out = shadow.grade_decision(d, box, {}, now=NOW + timedelta(days=1))
                self.assertEqual(out["result"], result)
                self.assertEqual(d_arm.grade_as, shadow.GRADE_RUN_LINE)

    def test_away_plus_one_and_a_half(self):
        d = self._lock_run_line(-150, 130, -175, 150)
        self.assertEqual((d["side"], d["line"]), ("away", 1.5))
        for (away, home), result in (((2, 3), "WIN"), ((1, 3), "LOSS"), ((5, 3), "WIN")):
            box = shadow.BoxIndex(batters={}, finals={GAME_PK: {(away, home, 9)}})
            out = shadow.grade_decision(d, box, {}, now=NOW + timedelta(days=1))
            self.assertEqual(out["result"], result, (away, home))

    def test_run_line_settles_from_the_linescore_sum(self):
        self._lock_run_line(130, -150, 150, -175)
        self.s.set_box([_linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        s = self.s.settled("C_RUN_LINE")[0]
        self.assertEqual((s["result"], s["away_score"], s["home_score"]), ("WIN", 1, 3))
        self.assertAlmostEqual(s["profit_units"], 1.5, places=4)

    def test_totals_grade_including_a_push_on_a_whole_line(self):
        rows = [_total(f"book{i}", 8.0, -110, -110) for i in range(5)]
        rows.append(_total("soft", 8.0, 110, -130))
        self.s.set_lines(rows)
        self.s.publish(arms=["D_GAME_TOTAL"])
        d = self.s.decisions("D_GAME_TOTAL")[0]
        for (away, home), result in (((4, 5), "WIN"), ((3, 4), "LOSS"), ((4, 4), "PUSH")):
            box = shadow.BoxIndex(batters={}, finals={GAME_PK: {(away, home, 9)}})
            out = shadow.grade_decision(d, box, {}, now=NOW + timedelta(days=1))
            self.assertEqual(out["result"], result, (away, home))

    def test_a_disagreeing_results_file_holds_the_grade_then_voids(self):
        self._lock_run_line(130, -150, 150, -175)
        self.s.set_box([_linescore(GAME_PK, 1, 3)])
        self.s.set_results([{"game_pk": GAME_PK, "date": DATE, "away_score": 1, "home_score": 2}])
        counts = self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(counts["C_RUN_LINE"]["mismatches"], 1)
        self.assertEqual(self.s.settled("C_RUN_LINE"), [])
        self.s.settle(now=NOW + timedelta(days=7))
        self.assertEqual(self.s.settled("C_RUN_LINE")[0]["reason"], "final score sources disagree")

    def test_an_agreeing_results_file_grades(self):
        self._lock_run_line(130, -150, 150, -175)
        self.s.set_box([_linescore(GAME_PK, 1, 3)])
        self.s.set_results([{"game_pk": GAME_PK, "date": DATE, "away_score": 1, "home_score": 3}])
        self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(self.s.settled("C_RUN_LINE")[0]["result"], "WIN")


class Records(Base):
    def test_records_are_per_arm_and_never_pooled(self):
        rows = [_spread(f"book{i}", -1.5, 130, -150) for i in range(5)]
        rows.append(_spread("soft", -1.5, 150, -175))
        self.s.set_lines(rows)
        self.s.set_props(_board("Jose Ramirez", 5))
        self.s.publish()
        self.s.set_box([_batter(GAME_PK, "Jose Ramirez", total_bases=0), _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        rec = shadow.record(ledger_dir=self.s.ledger)
        self.assertEqual(set(rec), {a.name for a in shadow.ARMS})
        self.assertEqual((rec["A_TOTAL_BASES"]["wins"], rec["A_TOTAL_BASES"]["losses"]), (0, 1))
        self.assertEqual((rec["C_RUN_LINE"]["wins"], rec["C_RUN_LINE"]["losses"]), (1, 0))
        self.assertAlmostEqual(rec["A_TOTAL_BASES"]["units"], -1.0)
        self.assertAlmostEqual(rec["C_RUN_LINE"]["roi_pct"], 150.0)
        self.assertEqual(rec["B_HITS"]["decisions"], 0)
        self.assertEqual(rec["A_TOTAL_BASES"]["days"], {"decided": 1})
        self.assertEqual(rec["D_GAME_TOTAL"]["days"], {"no board": 1})
        self.assertFalse([k for k in rec if "total" == k.lower() or "all" in k.lower()])

    def test_an_empty_day_says_which_kind_of_empty(self):
        self.s.set_props(_board("Cal Raleigh", 4))          # judged, too few books
        self.s.set_lines([_spread(f"book{i}", -1.5, 130, -150, minutes_ago=90) for i in range(6)]
                         + [_total(f"book{i}", 8.5, -110, -110) for i in range(6)])
        self.s.publish()
        rec = shadow.record(ledger_dir=self.s.ledger)
        # Only 4 other books on the line: nothing was compared, so the rule
        # did not "look and decline" -- it could not judge.
        self.assertEqual(rec["A_TOTAL_BASES"]["days"], {"too few books to judge any line": 1})
        # Six books at one price: lines were compared and none was value.
        self.assertEqual(rec["D_GAME_TOTAL"]["days"], {"looked and declined": 1})
        self.assertEqual(rec["C_RUN_LINE"]["days"], {"board too old to judge": 1})
        self.assertEqual(rec["B_HITS"]["days"], {"no board": 1})

    def test_settle_output_is_counts_only(self):
        from unittest import mock
        self.s.set_props(_board("Jose Ramirez", 5))
        self.s.publish()
        # The CLI reads the default box store: point the data root at a temp
        # dir so it reads this fixture and nothing on this machine.
        data_root = Path(self._tmp.name) / "data"
        _write_jsonl(data_root / "processed" / "boxscores_2026.jsonl",
                     [_batter(GAME_PK, "Jose Ramirez", total_bases=3), _linescore(GAME_PK, 1, 3)])
        buf = io.StringIO()
        with mock.patch.dict("os.environ", {"AISPORTS_DATA_DIR": str(data_root)}), \
                redirect_stdout(buf):
            shadow.main(["settle", "--recent", "--ledger-dir", str(self.s.ledger),
                         "--now", _z(NOW + timedelta(days=1)), "--dry-run"])
        text = buf.getvalue()
        self.assertIn("graded 1", text)
        for word in ("WIN", "LOSS", "units", "ROI"):
            self.assertNotIn(word, text)


# ---------------------------------------------------------------------------
# Corrections made before the first decision existed (prereg "Corrections")
# ---------------------------------------------------------------------------

class ShortenedGames(Base):
    """A game called before regulation is VOID on every arm. Books void run
    lines and totals unless 9 innings are played (8.5 with the home side
    ahead); a shortened game has fewer runs and fewer plate appearances, so
    grading it would hand Unders and run-line leaders wins no book pays."""

    def _lock_run_line_home(self):
        rows = [_spread(f"book{i}", -1.5, 130, -150) for i in range(5)]
        rows.append(_spread("soft", -1.5, 150, -175))
        self.s.set_lines(rows)
        self.s.publish(arms=["C_RUN_LINE"])
        d = self.s.decisions("C_RUN_LINE")[0]
        self.assertEqual((d["side"], d["line"]), ("home", -1.5))
        return d

    def _lock_total_under(self):
        rows = [_total(f"book{i}", 8.5, -110, -110) for i in range(5)]
        rows.append(_total("soft", 8.5, -130, 110))
        self.s.set_lines(rows)
        self.s.publish(arms=["D_GAME_TOTAL"])
        d = self.s.decisions("D_GAME_TOTAL")[0]
        self.assertEqual((d["side"], d["line"], d["price"]), ("under", 8.5, 110))
        return d

    def test_the_box_index_carries_the_innings_count(self):
        path = Path(self._tmp.name) / "box.jsonl"
        _write_jsonl(path, [_linescore(GAME_PK, 0, 3, innings_played=5)])
        box = shadow.load_box_index(["2026"], box_paths={"2026": path})
        self.assertEqual(box.finals[GAME_PK], {(0, 3, 5)})

    def test_a_five_inning_game_voids_the_run_line_and_the_total(self):
        self._lock_run_line_home()
        self._lock_total_under()
        self.s.set_box([_linescore(GAME_PK, 0, 3, innings_played=5)])
        self.s.set_results([{"game_pk": GAME_PK, "date": DATE, "away_score": 0, "home_score": 3}])
        counts = self.s.settle(now=NOW + timedelta(days=1))
        for arm in ("C_RUN_LINE", "D_GAME_TOTAL"):
            with self.subTest(arm=arm):
                self.assertEqual(counts[arm]["voids"], 1)
                s = self.s.settled(arm)[0]
                self.assertEqual((s["result"], s["reason"], s["profit_units"]),
                                 ("VOID", "game shortened", 0.0))
                self.assertEqual(s["innings"], 5)

    def test_a_shortened_game_voids_a_prop(self):
        self.s.set_props(_board("Jose Ramirez", 5))
        self.s.publish(arms=["A_TOTAL_BASES"])
        self.s.set_box([_batter(GAME_PK, "Jose Ramirez", total_bases=2),
                        _linescore(GAME_PK, 0, 3, innings_played=6)])
        self.s.settle(now=NOW + timedelta(days=1))
        s = self.s.settled("A_TOTAL_BASES")[0]
        self.assertEqual((s["result"], s["reason"]), ("VOID", "game shortened"))

    def test_regulation_is_a_ninth_inning_listed(self):
        """8 innings with the home side ahead has NOT reached 8.5: the top of
        the 9th was never played. A 9th inning listed with the home side
        ahead is the 8.5 case -- the store writes the unplayed bottom half as
        0 -- and it grades."""
        d = self._lock_run_line_home()
        for innings_played, result in ((5, "VOID"), (8, "VOID"), (9, "WIN"), (10, "WIN")):
            with self.subTest(innings=innings_played):
                path = Path(self._tmp.name) / f"box{innings_played}.jsonl"
                _write_jsonl(path, [_linescore(GAME_PK, 2, 5, innings_played=innings_played)])
                box = shadow.load_box_index(["2026"], box_paths={"2026": path})
                out = shadow.grade_decision(d, box, {}, now=NOW + timedelta(days=1))
                self.assertEqual(out["result"], result)
                self.assertEqual(out["innings"], innings_played)


class WithdrawnGameLineQuotes(Base):
    """A book missing from the board's newest capture instant is not quoted:
    the store writes every book the feed returns at every capture, so its
    absence means its price was not live at the decision."""

    FIRST = NOW                               # 20:00Z capture
    SECOND = NOW + timedelta(minutes=15)      # 20:15Z capture
    RUN = NOW + timedelta(minutes=16)

    def _row(self, book, over, under, *, observed, stamp):
        return {"observed_utc": observed.isoformat(), "event_id": EVENT,
                "commence_time": _z(FIRST_PITCH), "home_team": HOME, "away_team": AWAY,
                "market": "totals", "book": book, "book_last_update": _z(stamp),
                "total": "8.5", "over_price": over, "under_price": under}

    def _history(self, *, still_listed):
        books = [f"book{i}" for i in range(6)]
        rows = [self._row(b, -110, -110, observed=self.FIRST,
                          stamp=self.FIRST - timedelta(minutes=1))
                for b in books + ["betonlineag"]]
        rows += [self._row(b, -140, 118, observed=self.SECOND,
                           stamp=self.SECOND - timedelta(minutes=1)) for b in books]
        if still_listed:   # listed again at 20:15, its own stamp unchanged
            rows.append(self._row("betonlineag", -110, -110, observed=self.SECOND,
                                  stamp=self.FIRST - timedelta(minutes=1)))
        return rows

    def test_a_book_absent_from_the_newest_capture_is_not_judged(self):
        self.s.set_lines(self._history(still_listed=False))
        out = self.s.publish(arms=["D_GAME_TOTAL"], now=self.RUN, dry_run=True)
        self.assertEqual(out["D_GAME_TOTAL"]["decisions"], [])
        self.assertEqual(out["D_GAME_TOTAL"]["counts"]["candidates"], 0)
        # Control: the SAME price, still listed at 20:15 with its old stamp,
        # is live and is judged. Only the book's presence differs.
        self.s.set_lines(self._history(still_listed=True))
        self.s.publish(arms=["D_GAME_TOTAL"], now=self.RUN)
        rows = self.s.decisions("D_GAME_TOTAL")
        self.assertEqual([(d["book"], d["side"], d["price"]) for d in rows],
                         [("betonlineag", "over", -110)])

    def test_a_withdrawn_book_is_not_in_anyone_elses_consensus(self):
        # At 20:15 five books remain plus a soft one. The withdrawn book
        # would have made the soft book's sixth "other"; without it the soft
        # book has only 5 others -- still enough -- but its fair price comes
        # from the five live books alone.
        books = [f"book{i}" for i in range(5)]
        rows = [self._row(b, -110, -110, observed=self.FIRST,
                          stamp=self.FIRST - timedelta(minutes=1)) for b in books + ["gone"]]
        rows += [self._row(b, -110, -110, observed=self.SECOND,
                           stamp=self.SECOND - timedelta(minutes=1)) for b in books]
        rows.append(self._row("soft", 110, -130, observed=self.SECOND,
                              stamp=self.SECOND - timedelta(minutes=1)))
        self.s.set_lines(rows)
        self.s.publish(arms=["D_GAME_TOTAL"], now=self.RUN)
        d = self.s.decisions("D_GAME_TOTAL")[0]
        self.assertEqual(d["book"], "soft")
        self.assertEqual(d["other_books"], sorted(books))


class KnownLimitsAreTrue(unittest.TestCase):
    def test_dropping_a_non_updating_book_can_create_a_candidate_and_the_prereg_says_so(self):
        """The prop store writes no row when a book's stamp is unchanged, so
        a book whose market did not move can fail the 30-minute book test.
        Removing it from the consensus moves the fair price EITHER way: here
        it creates a candidate that the full consensus refused."""
        params = shadow.ARMS_BY_NAME["A_TOTAL_BASES"].params
        fresh = NOW - timedelta(minutes=5)

        def quote(book, over, under, when):
            return {"book": book, "line_key": ("cal raleigh", "1.5"),
                    "pair": (("over", 1.5, over), ("under", 1.5, under)),
                    "quote_time": when, "meta": {}}

        board = [quote("draftkings", 180, -250, fresh)]
        board += [quote(b, 150, -195, fresh)
                  for b in ("betmgm", "williamhill_us", "bovada", "betonlineag", "fanatics")]
        with_it = board + [quote("mybookieag", 175, -225, fresh)]
        without_it = board + [quote("mybookieag", 175, -225, NOW - timedelta(hours=6))]

        self.assertEqual(lobo.judge_board(with_it, now=NOW, params=params)["candidates"], [])
        cands = lobo.judge_board(without_it, now=NOW, params=params)["candidates"]
        self.assertEqual([(c["book"], c["side"], c["price"]) for c in cands],
                         [("draftkings", "over", 180)])

        text = " ".join(PREREG.read_text(encoding="utf-8").split())
        self.assertNotIn("can only remove books, never add value", text)
        self.assertIn("can move the fair price either way", text)


class NameJoinFallback(Base):
    def _lock(self, player, market="batter_total_bases", line="1.5"):
        arm = "A_TOTAL_BASES" if market == "batter_total_bases" else "B_HITS"
        n = 5 if arm == "A_TOTAL_BASES" else 2
        self.s.set_props(_board(player, n, market=market, line=line))
        self.s.publish(arms=[arm])
        self.assertEqual(len(self.s.decisions(arm)), 1)
        return arm

    def test_a_box_score_nickname_grades_by_first_name_prefix(self):
        # batter_props says "Leonardo Bernal"; the box score says "Leo Bernal".
        arm = self._lock("Leonardo Bernal")
        self.s.set_box([_batter(GAME_PK, "Leo Bernal", player_id=699024, total_bases=4),
                        _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        s = self.s.settled(arm)[0]
        self.assertEqual((s["result"], s["stat_value"]), ("WIN", 4))
        self.assertEqual((s["name_join"], s["box_player_id"], s["box_player_name"]),
                         ("first_name_prefix", 699024, "Leo Bernal"))

    def test_the_exact_join_is_used_first_and_recorded(self):
        arm = self._lock("Leo Bernal")
        self.s.set_box([_batter(GAME_PK, "Leo Bernal", player_id=1, total_bases=0),
                        _batter(GAME_PK, "Leonardo Bernal", player_id=2, total_bases=4),
                        _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        s = self.s.settled(arm)[0]
        self.assertEqual((s["result"], s["name_join"], s["box_player_id"]), ("LOSS", "exact", 1))

    def test_a_different_first_name_is_never_joined(self):
        # Colson Montgomery's prop, Braden Montgomery in the box: a wrong-player
        # grade would be worse than a void.
        arm = self._lock("Colson Montgomery")
        self.s.set_box([_batter(GAME_PK, "Braden Montgomery", pa=3, h=0, total_bases=0),
                        _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        s = self.s.settled(arm)[0]
        self.assertEqual((s["result"], s["reason"], s["name_join"]), ("VOID", "did not bat", None))

    def test_two_prefix_matches_are_ambiguous(self):
        arm = self._lock("Alex Smith")
        self.s.set_box([_batter(GAME_PK, "Alexander Smith", player_id=1),
                        _batter(GAME_PK, "Alexis Smith", player_id=2),
                        _linescore(GAME_PK, 1, 3)])
        self.s.settle(now=NOW + timedelta(days=1))
        self.assertEqual(self.s.settled(arm)[0]["reason"], "ambiguous name")

    def test_the_prefix_rule(self):
        cases = {("leonardo bernal", "leo bernal"): True,
                 ("leo bernal", "leonardo bernal"): True,
                 ("colson montgomery", "braden montgomery"): False,
                 ("leonardo bernal", "leo bernard"): False,
                 ("al smith", "albert smith"): False,         # under 3 letters: never
                 ("bernal", "bernal"): False,                 # one token: never
                 ("leo bernal", "leo bernal"): False}         # the exact join's job
        for (a, b), expected in cases.items():
            self.assertEqual(shadow.first_name_prefix_match(a, b), expected, (a, b))


class OneBrokenArmStopsNoOther(Base):
    """A line JSON cannot parse (a leftover conflict marker, a truncated
    append) in one arm's ledger fails that arm only, loudly."""

    def _run_line_board(self):
        rows = [_spread(f"book{i}", -1.5, 130, -150) for i in range(5)]
        rows.append(_spread("soft", -1.5, 150, -175))
        self.s.set_lines(rows)

    def _corrupt(self, arm_name, kind="decisions"):
        arm = shadow.ARMS_BY_NAME[arm_name]
        path = {"decisions": shadow.decisions_path, "settled": shadow.settled_path,
                "scans": shadow.scans_path}[kind](self.s.ledger, arm)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("<<<<<<< HEAD\n")

    def test_publish_goes_on_to_the_other_arms(self):
        self._corrupt("A_TOTAL_BASES")
        self._run_line_board()
        out = self.s.publish()
        self.assertIn("error", out["A_TOTAL_BASES"])
        self.assertEqual(len(self.s.decisions("C_RUN_LINE")), 1)
        self.assertEqual(out["C_RUN_LINE"]["counts"]["new_decisions"], 1)
        self.assertEqual(len(self.s.scans("B_HITS")), 1)

    def test_settle_goes_on_to_the_other_arms(self):
        self._run_line_board()
        self.s.publish()
        self._corrupt("A_TOTAL_BASES")
        self.s.set_box([_linescore(GAME_PK, 1, 3)])
        counts = self.s.settle(now=NOW + timedelta(days=1))
        self.assertIn("error", counts["A_TOTAL_BASES"])
        self.assertEqual(counts["C_RUN_LINE"]["graded"], 1)
        self.assertEqual(self.s.settled("C_RUN_LINE")[0]["result"], "WIN")

    def test_record_and_verify_go_on_to_the_other_arms(self):
        self._run_line_board()
        self.s.publish()
        self._corrupt("A_TOTAL_BASES", "scans")
        rec = shadow.record(ledger_dir=self.s.ledger)
        self.assertIn("error", rec["A_TOTAL_BASES"])
        self.assertEqual(rec["C_RUN_LINE"]["decisions"], 1)
        v = shadow.verify(ledger_dir=self.s.ledger)
        self.assertFalse(v["A_TOTAL_BASES_scans.jsonl"]["ok"])
        self.assertTrue(v["C_RUN_LINE_decisions.jsonl"]["ok"])

    def test_the_cli_names_the_broken_arm_and_exits_nonzero(self):
        from unittest import mock
        self._corrupt("A_TOTAL_BASES")
        data_root = Path(self._tmp.name) / "data"
        _write_jsonl(data_root / "processed" / "event_game_map.jsonl", [_map_row(EVENT, GAME_PK)])
        rows = [_spread(f"book{i}", -1.5, 130, -150) for i in range(5)]
        rows.append(_spread("soft", -1.5, 150, -175))
        _write_jsonl(data_root / "processed" / "odds_multibook.jsonl", rows)
        for command in (["publish", "--date", DATE, "--now", _z(NOW)],
                        ["settle", "--recent", "--now", _z(NOW + timedelta(days=1))],
                        ["record"], ["verify"]):
            with self.subTest(command=command[0]):
                buf = io.StringIO()
                with mock.patch.dict("os.environ", {"AISPORTS_DATA_DIR": str(data_root)}), \
                        redirect_stdout(buf):
                    code = shadow.main(command + ["--ledger-dir", str(self.s.ledger)])
                text = buf.getvalue()
                self.assertEqual(code, 1, text)
                self.assertIn("A_TOTAL_BASES", text)
                self.assertTrue(re.search(r"A_TOTAL_BASES\S*: .*(ERROR|BROKEN)", text), text)
                if command[0] == "publish":
                    self.assertIn("C_RUN_LINE: boards 1", text)


class RecordSaysWhichKindOfEmpty(Base):
    def _run_line_board(self):
        rows = [_spread(f"book{i}", -1.5, 130, -150) for i in range(5)]
        rows.append(_spread("soft", -1.5, 150, -175))
        self.s.set_lines(rows)

    def test_value_dropped_by_an_unmapped_game_is_not_looked_and_declined(self):
        self.s.set_map([_map_row(EVENT2, GAME_PK2)])        # EVENT has no game_pk
        self._run_line_board()
        out = self.s.publish(arms=["C_RUN_LINE"])
        c = out["C_RUN_LINE"]["counts"]
        self.assertEqual((c["candidates"], c["skipped_unmapped"], c["new_decisions"]), (1, 1, 0))
        rec = shadow.record(ledger_dir=self.s.ledger)["C_RUN_LINE"]
        self.assertEqual(rec["days"], {"value found but game unmapped or ambiguous": 1})
        self.assertEqual((rec["skipped_unmapped"], rec["skipped_ambiguous"], rec["capped"]),
                         (1, 0, 0))

    def test_value_on_a_doubleheader_is_not_looked_and_declined(self):
        self.s.set_map([_map_row(EVENT, GAME_PK, ambiguous=True)])
        self.s.set_props(_board("Cal Raleigh", 5))
        self.s.publish(arms=["A_TOTAL_BASES"])
        rec = shadow.record(ledger_dir=self.s.ledger)["A_TOTAL_BASES"]
        self.assertEqual(rec["days"], {"value found but game unmapped or ambiguous": 1})
        self.assertEqual(rec["skipped_ambiguous"], 1)

    def test_skip_and_cap_totals_are_per_date_peaks_not_run_sums(self):
        self.s.set_map([_map_row(EVENT2, GAME_PK2)])
        self._run_line_board()
        self.s.publish(arms=["C_RUN_LINE"])
        # A later run the same day with a different count appends a second
        # scan row; the same skipped key must not be counted twice.
        rows = [_spread(f"book{i}", -1.5, 130, -150, now=NOW + timedelta(minutes=5))
                for i in range(6)]
        rows.append(_spread("soft", -1.5, 150, -175, now=NOW + timedelta(minutes=5)))
        self.s.set_lines(rows)
        self.s.publish(arms=["C_RUN_LINE"], now=NOW + timedelta(minutes=5))
        self.assertEqual(len(self.s.scans("C_RUN_LINE")), 2)
        self.assertEqual(shadow.record(ledger_dir=self.s.ledger)["C_RUN_LINE"]["skipped_unmapped"], 1)

    def test_the_record_printout_shows_the_skips(self):
        self.s.set_map([_map_row(EVENT2, GAME_PK2)])
        self._run_line_board()
        self.s.publish(arms=["C_RUN_LINE"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            shadow.main(["record", "--ledger-dir", str(self.s.ledger)])
        line = next(l for l in buf.getvalue().splitlines() if "C_RUN_LINE" in l)
        self.assertIn("unmapped 1", line)
        self.assertIn("value found but game unmapped or ambiguous 1", line)


# ---------------------------------------------------------------------------
# Registration and isolation
# ---------------------------------------------------------------------------

# Corrected before the first decision existed (prereg "Corrections"): the
# constants now carry regulation_innings and name_prefix_min_letters.
REGISTERED_SHA256 = {
    "A_TOTAL_BASES": "508219c4a2fcb4515651b0572a7f71cdf03604e6eb9d6f2798ca29f6b7ec3d15",
    "B_HITS": "7a2fa3f8bfa965ca29ddf61bf4f41bc790014dfe3690e98a07e7a8cfae21c01c",
    "C_RUN_LINE": "426cb4e8e4d521a4a5bab7c4c0849e0a7f01751a3f2221112c61e7e11f13e63b",
    "D_GAME_TOTAL": "bfe53c9be5018ec80cf0f4f10b3faf00d0059b4e3acb7f74e9b0fab263a327dc",
}
PREREG = ROOT / "docs" / "PREREG_MLB_VALUE_SHADOW_V1.md"


class Registration(unittest.TestCase):
    def test_each_arms_constants_match_the_registration(self):
        text = PREREG.read_text(encoding="utf-8")
        for arm in shadow.ARMS:
            with self.subTest(arm=arm.name):
                self.assertEqual(arm.constants_sha256(), REGISTERED_SHA256[arm.name])
                self.assertIn(REGISTERED_SHA256[arm.name], text)
                self.assertIn(arm.rule_id, text)

    def test_the_registered_numbers(self):
        self.assertEqual(shadow.WORST_PRICE, -200)
        self.assertEqual(shadow.MIN_EV, 0.02)
        self.assertEqual((shadow.FRESH_SECONDS, shadow.FRESH_BOARD_SECONDS), (1800, 3600))
        self.assertEqual({a.name: a.params.min_other_books for a in shadow.ARMS},
                         {"A_TOTAL_BASES": 5, "B_HITS": 2, "C_RUN_LINE": 5, "D_GAME_TOTAL": 5})
        self.assertEqual(shadow.LOCK_LEAD_HOURS, 4.0)
        self.assertEqual(shadow.MAX_PER_DATE, 15)
        self.assertEqual(shadow.VOID_AFTER_DAYS, 7)
        self.assertEqual(shadow.REGULATION_INNINGS, 9)
        self.assertEqual(shadow.NAME_PREFIX_MIN_LETTERS, 3)
        for arm in shadow.ARMS:
            self.assertEqual(tuple(arm.params.devig_methods), ("proportional", "shin", "power"))

    def test_the_decision_row_carries_the_constants_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Stores(tmp)
            s.set_props(_board("Cal Raleigh", 5))
            s.publish(arms=["A_TOTAL_BASES"])
            self.assertEqual(s.decisions("A_TOTAL_BASES")[0]["constants_sha256"],
                             REGISTERED_SHA256["A_TOTAL_BASES"])


class Isolation(unittest.TestCase):
    PROTECTED = ("evidence/cards_v1.jsonl", "evidence/decisions_v2.jsonl",
                 "evidence/cards_nfl_v1.jsonl", "evidence/paper_wagers_v2.jsonl")

    def _sha(self, rel):
        p = ROOT / rel
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None

    def test_publish_and_settle_leave_the_card_and_engine_stores_byte_identical(self):
        before = {rel: self._sha(rel) for rel in self.PROTECTED}
        with tempfile.TemporaryDirectory() as tmp:
            s = Stores(tmp)
            rows = [_spread(f"book{i}", -1.5, 130, -150) for i in range(5)]
            rows.append(_spread("soft", -1.5, 150, -175))
            s.set_lines(rows)
            s.set_props(_board("Jose Ramirez", 5))
            s.publish()
            s.set_box([_batter(GAME_PK, "Jose Ramirez"), _linescore(GAME_PK, 1, 3)])
            s.settle(now=NOW + timedelta(days=1))
            shadow.record(ledger_dir=s.ledger)
        self.assertEqual(before, {rel: self._sha(rel) for rel in self.PROTECTED})

    def test_importing_the_shadow_loads_no_provider_module(self):
        code = ("import sys; import src.analysis.mlb_value_shadow as m; "
                "m.load_box_index([]); import src.appstate.card_ledger, src.board.settle_props; "
                "bad = sorted(k for k in sys.modules if k.startswith('src.providers') "
                "or k.startswith('src.report') or k.startswith('src.engine')); print(bad)")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                             text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[]")

    def test_the_shadow_source_imports_nothing_customer_facing_or_paid(self):
        for mod in (shadow, lobo):
            tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    names.add(node.module or "")
            bad = [n for n in names if n.startswith(("src.providers", "src.report", "src.engine",
                                                     "api", "src.pipeline", "src.capture"))]
            self.assertEqual(bad, [], mod.__name__)

    def test_no_customer_surface_imports_the_shadow(self):
        pattern = re.compile(r"mlb_value_shadow|lobo_value")
        hits = []
        for folder in ("api", "src/report", "web", "site"):
            base = ROOT / folder
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if path.suffix in (".py", ".js", ".html", ".ts") and path.is_file():
                    if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                        hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [])


class Parity(unittest.TestCase):
    def test_official_date_matches_the_capture_modules(self):
        from src.pipeline.snapshots import official_date
        for value in ("2026-09-22T01:46:00Z", "2026-09-21T16:05:00Z", "2026-09-21T03:59:00+00:00",
                      "2026-09-21T04:00:00Z", "2026-09-21", None, "garbage"):
            self.assertEqual(shadow.official_date(value), official_date(value), value)

    def test_game_map_matches_gamekey(self):
        from src.board import gamekey
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.jsonl"
            _write_jsonl(path, [
                {"event_id": "e1", "game_pk": 123, "ambiguous": False},
                {"event_id": "e2", "game_pk": "456", "ambiguous": True},
                {"event_id": "e1", "game_pk": " 789 ", "ambiguous": False},
                {"event_id": "e3", "game_pk": None, "ambiguous": False},
            ])
            ours, theirs = shadow.load_game_map(path), gamekey.load_map(path)
            self.assertEqual(ours, theirs)
            for event in ("e1", "e2", "e3", "missing"):
                expected = gamekey.game_pk_for_event(event, theirs)
                gpk, reason = shadow.map_event(event, ours)
                if reason == "ambiguous":
                    self.assertIsNotNone(expected)
                else:
                    self.assertEqual(gpk, expected, event)

    def test_name_normalisation(self):
        cases = {
            "José Ramírez": "jose ramirez",
            "Bobby Witt Jr.": "bobby witt",
            "Max Muncy (2002)": "max muncy",
            "Ha-Seong Kim": "ha seong kim",
            "Travis d'Arnaud": "travis darnaud",
            "J.P. Crawford": "jp crawford",
            "Vladimir Guerrero Jr.": "vladimir guerrero",
            "Cal  Raleigh": "cal raleigh",
            "Luis Robert Jr": "luis robert",
            "Ken Griffey III": "ken griffey",
        }
        for raw, expected in cases.items():
            self.assertEqual(shadow.norm_name(raw), expected, raw)


class Cli(unittest.TestCase):
    def test_publish_dry_run_prints_and_writes_nothing(self):
        # The data root is redirected to a temp dir holding one fixture board,
        # so the CLI's default store paths read nothing from this machine.
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            processed = Path(tmp) / "processed"
            _write_jsonl(processed / "batter_props.jsonl", _board("Cal Raleigh", 5))
            _write_jsonl(processed / "event_game_map.jsonl", [_map_row(EVENT, GAME_PK)])
            ledger = Path(tmp) / "ledger"
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"AISPORTS_DATA_DIR": tmp}), redirect_stdout(buf):
                self.assertEqual(shadow.default_props_path(), processed / "batter_props.jsonl")
                code = shadow.main(["publish", "--date", DATE, "--dry-run",
                                    "--ledger-dir", str(ledger), "--now", _z(NOW)])
            self.assertEqual(code, 0)
            text = buf.getvalue()
            self.assertIn("DRY RUN", text)
            self.assertIn("WOULD LOCK A_TOTAL_BASES", text)
            self.assertIn("Cal Raleigh Over 1.5 +110 @ soft", text)
            for arm in shadow.ARMS:
                self.assertIn(f"{arm.name}: boards", text)
            self.assertFalse(ledger.exists())

    def test_unknown_arm_is_refused(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = shadow.main(["publish", "--date", DATE, "--dry-run", "--arms", "Z_NOPE"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
