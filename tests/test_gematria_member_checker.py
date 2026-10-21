"""Checker's adversarial pins for the member "Gematria" style (2026-10-21), on top of tests/test_gematria_member_style.py.

  parity     the member's pass and the house runner, on the SAME stores and the SAME runtime, write the same decision AND the same
             whole evidence block (not just the scores), and the row stamps rules_version / rules_hash
  lock time  a price captured AFTER the lock (and before the start) and a final score first seen AFTER the lock are planted; the
             bet, its price and its evidence are byte-identical to the run without them, and a plant that would turn a pass into a
             bet (a post-lock price inside the band) cannot
  -200       a lock-time price of -200 or worse is a pass even when a post-lock price is inside the band
  one side   the one-side-per-game guard (src/hounds/one_side.py) holds a member Gematria bet too: a ticket already on the other side
             of the game (or the same side) stops it, and the pass leaves no second row
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from src.hounds import one_side, user_engine, user_gematria
from src.hounds.gematria import history, runtime as rt
from src.hounds.pack import base
from tests.test_ai_hounds import NOW_AS, START_AS, allsports_rows, allsports_stores, nba_rows
from tests.test_gematria_hound import LENIENT, NBA_FACTS, G, make_rules, season_games
from tests.test_gematria_member_style import DATE, EngineCase, member, runtime_factory


def _late(eid, home_ml, away_ml, at):
    """A whole-board capture at ``at`` (after the lock, before the start) for the standard NBA game."""
    from tests.test_house_pack_hounds import game_rows

    rows = game_rows(eid, START_AS, away="Boston Celtics", home="New York Knicks", sport="nba", observed=at, home_ml=home_ml,
                     away_ml=away_ml, spread=(-1.5, -110, -110), total=(221.5, -110, -110))
    for r in rows:
        r["league"], r["league_title"] = "nba_test_league", "NBA"
    return rows


LOCK = START_AS - timedelta(minutes=60)        # 22:15


class ParityTests(EngineCase):
    def test_the_whole_evidence_block_equals_the_house_runners(self):
        runtime = runtime_factory()()
        stores = allsports_stores(nba_rows())
        ctx = base.build_context(stores, "nba1")
        house = runtime.weigh(ctx, base.lock_board(stores, ctx))
        self.run_engine([member()])
        (row,) = self.bets()
        self.assertEqual(row["gematria"], house.block)
        self.assertEqual((row["rules_version"], row["rules_hash"]), (runtime.rules.version, runtime.rules.rules_hash))
        self.assertEqual((row["side"], row["price_average"]), (house.verdict.side, house.verdict.price))

    def test_two_member_hounds_with_different_choices_get_the_same_decision(self):
        a, b = member("u-a", max_bets_per_day=1, stake_units=1.0), member("u-b", max_bets_per_day=5, stake_units=3.0)
        self.run_engine([a, b])
        rows = {r["hound_id"]: r for r in self.bets()}
        for key in ("side", "price_average", "gematria", "rules_hash", "reason", "confidence", "selection"):
            self.assertEqual(rows["u-a"][key], rows["u-b"][key], key)


class LockTimeOnlyTests(EngineCase):
    def baseline(self):
        self.run_engine([member()])
        (row,) = self.bets()
        return row

    def test_a_price_captured_after_the_lock_changes_nothing(self):
        base_row = self.baseline()
        for p in (Path(self.ledger),):
            p.unlink()
        planted = nba_rows() + _late("nba1", -400, -450, LOCK + timedelta(minutes=5)) + _late("nba1", 500, 500, LOCK + timedelta(minutes=14))
        out = self.run_engine([member()], rows=planted)
        self.assertEqual(out["bets_written"], 1)
        (row,) = self.bets()
        for key in ("side", "price_average", "price", "best_price", "gematria", "board_observed_utc", "reason", "rules_hash"):
            self.assertEqual(row.get(key), base_row.get(key), key)

    def test_a_post_lock_price_inside_the_band_cannot_turn_a_minus_250_pass_into_a_bet(self):
        fav = allsports_rows("nba1", "nba", "Boston Celtics", "New York Knicks", title="NBA", home_ml=210, away_ml=-250,
                             spread=(-1.5, -110, -110), total=(221.5, -110, -110))
        planted = fav + _late("nba1", 210, 105, LOCK + timedelta(minutes=3))
        out = self.run_engine([member()], rows=planted)
        self.assertEqual((out["bets_written"], out["skipped"]), (0, {"gematria_outside_band": 1}))
        self.assertEqual(self.bets(), [])

    def test_a_final_score_first_seen_after_the_lock_changes_nothing(self):
        """The real history source (history.Disk on an ESPN store folder): a game that started before the lock and whose final
        was observed after it is post-lock information. The evidence is identical with and without it."""
        def build(root, plant):
            folder = Path(root) / "nba"
            folder.mkdir(parents=True)
            rows = []
            for i, x in enumerate(season_games()):
                rows.append({"game_id": f"g{i}", "completed": True, "date_utc": x.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "observed_utc": (x.start + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "home_name": _name(x.home), "away_name": _name(x.away), "home_score": x.hs, "away_score": x.as_,
                             "season_slug": "regular-season"})
            if plant:        # started 21:30 (before the 22:15 lock), final first seen 22:20 (after it): the Celtics lose big
                rows.append({"game_id": "late", "completed": True, "date_utc": "2026-10-20T21:30:00Z",
                             "observed_utc": "2026-10-20T22:20:00Z", "home_name": "Boston Celtics", "away_name": "Denver Nuggets",
                             "home_score": 60, "away_score": 130, "season_slug": "regular-season"})
                rows.append({"game_id": "tomorrowfinal", "completed": True, "date_utc": "2026-10-20T23:15:00Z",
                             "observed_utc": "2026-10-21T02:00:00Z", "home_name": "New York Knicks", "away_name": "Boston Celtics",
                             "home_score": 90, "away_score": 120, "season_slug": "regular-season"})
            (folder / "games_2027.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

        def names():
            return {"bostonceltics": "Boston Celtics", "newyorkknicks": "New York Knicks"}

        def _name(tid):
            return names().get(tid) or tid

        blocks = []
        for plant in (False, True):
            with tempfile.TemporaryDirectory() as d:
                build(d, plant)
                disk = history.Disk(espn=history.EspnStore(Path(d)), canonical=lambda s, n: n)
                factory = lambda disk=disk: rt.GematriaRuntime(rules=make_rules(**LENIENT), facts=NBA_FACTS, source=disk, ledger=None,
                                                              now_fn=lambda: NOW_AS)
                Path(self.ledger).unlink(missing_ok=True)
                self.run_engine([member()], factory=factory)
                blocks.append([r["gematria"] for r in self.bets()])
        self.assertEqual(blocks[0], blocks[1])


class OneSideGuardTests(EngineCase):
    def prior(self, market, side, line=None):
        row = {"kind": user_engine.KIND_BET, "bet_id": "manual-x", "hound_id": "u-gem1", "event_id": "nba1", "sport": "NBA",
               "market": market, "side": side, "line": line, "home_team": "New York Knicks", "away_team": "Boston Celtics",
               "commence_time": "2026-10-20T23:15:00Z", "slate_date": DATE}
        Path(self.ledger).write_text(json.dumps(row) + "\n", encoding="utf-8")

    def test_a_ticket_on_the_other_side_stops_the_gematria_bet(self):
        # the engine would back the away Celtics; the hound already holds the home Knicks -1.5
        self.prior("spread", "home", -1.5)
        out = self.run_engine([member()])
        self.assertEqual(out["bets_written"], 0, out)
        self.assertTrue(any(k.startswith("one_side") for k in out["skipped"]), out["skipped"])
        self.assertEqual([r for r in self.bets() if r["bet_id"] != "manual-x"], [])

    def test_a_ticket_on_the_same_side_makes_the_second_redundant(self):
        self.prior("moneyline", "away")
        out = self.run_engine([member()])
        self.assertEqual(out["bets_written"], 0, out)
        self.assertEqual(out["skipped"].get(one_side.CODE_SAME), 1)

    def test_a_second_pass_after_a_bet_cannot_add_a_second_side(self):
        self.run_engine([member()])
        flipped = nba_rows() + _late("nba1", 100, -120, LOCK - timedelta(minutes=1))
        out = self.run_engine([member()], rows=flipped)
        self.assertEqual(out["bets_written"], 0)
        self.assertEqual(len([r for r in self.bets()]), 1)


if __name__ == "__main__":
    unittest.main()
