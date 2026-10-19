"""The hindsight drill (src/hounds/interact/drill.py): read only, labelled, never counted. No FastAPI needed.

The fixture slate is 2026-10-20 (tests/_hounds_user_fixtures.py): Boston at Seattle, the away side an underdog at
+120 at the lock board. Asked on 2026-10-22, a 7-day drill covers 2026-10-15 .. 2026-10-21 and sees that game.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from src.hounds import user_engine as eng
from src.hounds import user_spec
from src.hounds.interact import common, drill
from tests._hounds_user_fixtures import DATE, EVENT, hound, result_row, spec_dict, standard_rows, utc

NOW = utc("2026-10-22T12:00:00Z")
PK = "900001"
INDEX = {EVENT: {"game_pk": PK}}
RESULTS = {PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)}            # Boston (away) wins


def user_dog(**over) -> common.Dog:
    h = hound("u-drill", **over)
    h.update({"owner_user_id": 3, "status": "running", "name": "Dog Days", "tagline": "", "root_id": "u-drill"})
    return common.Dog(id="u-drill", kind=common.KIND_USER, name="Dog Days", hound=h, owner_user_id=3,
                      status="running", root_id="u-drill")


def rows_by_date():
    return {DATE: standard_rows()}


def run(dog=None, spec=None, days=7, **kw):
    inject = dict(rows_by_date=rows_by_date(), mlb_results=RESULTS, nfl_results=lambda d: {}, game_pk_index=INDEX)
    inject.update(kw)
    return drill.drill(days=days, dog=dog, spec=spec, now=NOW, **inject)


class TheDrill(unittest.TestCase):
    def setUp(self):
        drill.clear_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_user_v1.jsonl")
        patch = mock.patch.object(eng, "ledger_path", lambda p=None: p or self.ledger)
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_replays_the_rule_and_reports_wins_losses_and_units(self):
        out = run(user_dog())
        self.assertEqual(out["record"], {"bets": 1, "graded": 1, "wins": 1, "losses": 0, "pushes": 0, "voids": 0, "pending": 0})
        self.assertEqual(out["units_average_price"], 1.2)               # +120, the board average
        self.assertEqual(out["units_best_price"], 1.2)
        self.assertEqual(out["picks"][0]["selection"], "Boston Red Sox to win")
        self.assertEqual(out["picks"][0]["result"], "WIN")
        self.assertEqual(out["best"][0]["units_average_price"], 1.2)
        self.assertEqual(out["worst"], [])
        self.assertEqual(out["window"], {"first": "2026-10-15", "last": "2026-10-21"})
        self.assertEqual(out["days"], 7)

    def test_a_loss_is_a_worst_pick(self):
        out = run(user_dog(), mlb_results={PK: result_row(PK, DATE, "BOS", "SEA", 1, 3)})
        self.assertEqual((out["record"]["wins"], out["record"]["losses"], out["units_average_price"]), (0, 1, -1.0))
        self.assertEqual(out["worst"][0]["selection"], "Boston Red Sox to win")

    def test_it_is_labelled_hindsight_and_not_counted_everywhere_it_matters(self):
        out = run(user_dog())
        self.assertEqual(out["label"], "Hindsight drill: not counted")
        self.assertIs(out["counted"], False)
        self.assertIn("never added to a record", out["disclosure"])
        self.assertIn("rehearsal", out["disclosure"])
        self.assertTrue(out["small_sample"])
        self.assertIn("small sample", out["sample_note"])
        self.assertTrue(out["paper_only"])

    def test_it_is_read_only_no_ledger_no_database_no_leftover_files(self):
        before = set(os.listdir(self._tmp.name))
        tmp_before = set(os.listdir(tempfile.gettempdir()))
        run(user_dog())
        run(spec=spec_dict(name="Typed rule"))
        self.assertEqual(set(os.listdir(self._tmp.name)), before)
        self.assertFalse(os.path.exists(self.ledger))
        self.assertFalse(any(n.startswith("tmp") and n not in tmp_before and os.path.isfile(os.path.join(tempfile.gettempdir(), n))
                             for n in os.listdir(tempfile.gettempdir())))

    def test_the_drill_does_not_see_the_dogs_real_tickets_or_add_to_them(self):
        eng.run(DATE, [hound("u-drill")], standard_rows(), ledger=self.ledger, now=utc("2026-10-20T21:10:00Z"))
        real = open(self.ledger, "rb").read()
        out = run(user_dog())
        self.assertEqual(out["record"]["bets"], 1)                       # its own replay, not the ledger's row
        self.assertEqual(open(self.ledger, "rb").read(), real)

    def test_a_typed_in_spec_is_validated_like_a_created_dog(self):
        out = run(spec=spec_dict(name="Typed rule"))
        self.assertEqual(out["dog"]["kind"], "spec")
        self.assertEqual(out["record"]["bets"], 1)
        self.assertIn("MLB moneylines", out["rule_text"])
        with self.assertRaises(drill.DrillError) as ctx:
            run(spec=spec_dict(price_min=-250, price_max=-210))
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("spec_invalid", 422))
        self.assertIn("price_min", ctx.exception.fields)
        with self.assertRaises(drill.DrillError):
            run(spec={"side_rule": "teleport"})

    def test_a_spec_needs_no_name(self):
        raw = spec_dict()
        raw.pop("name")
        raw.pop("tagline")
        self.assertEqual(run(spec=raw)["record"]["bets"], 1)

    def test_only_7_14_or_30_days(self):
        for good in (7, 14, 30):
            self.assertEqual(drill.window(good, NOW)[1], "2026-10-21")
        for bad in (0, 1, 5, 31, 60, -7):
            with self.assertRaises(drill.DrillError) as ctx:
                drill.window(bad, NOW)
            self.assertEqual((ctx.exception.code, ctx.exception.status), ("days_invalid", 422))

    def test_the_window_is_completed_days_only_never_today(self):
        self.assertEqual(drill.window(7, NOW), ("2026-10-15", "2026-10-21"))
        self.assertEqual(drill.window(30, NOW), ("2026-09-22", "2026-10-21"))

    def test_a_game_outside_the_window_is_not_replayed(self):
        out = run(user_dog(), days=7, rows_by_date={"2026-09-01": standard_rows()})
        self.assertEqual(out["record"]["bets"], 0)

    def test_exactly_one_target(self):
        with self.assertRaises(drill.DrillError):
            drill.drill(days=7, now=NOW)
        with self.assertRaises(drill.DrillError):
            drill.drill(days=7, dog=user_dog(), spec=spec_dict(), now=NOW)

    def test_an_ai_desk_dog_cannot_be_drilled(self):
        with self.assertRaises(drill.DrillError) as ctx:
            drill.drill(days=7, dog=common.Dog(id="desk", kind=common.KIND_OTHER, name="Desk"), now=NOW)
        self.assertEqual(ctx.exception.code, "not_drillable")

    def test_it_is_deterministic(self):
        a, b = run(user_dog()), run(user_dog())
        for key in ("record", "units_average_price", "picks", "best", "worst"):
            self.assertEqual(a[key], b[key])

    def test_it_uses_the_daily_cap_of_the_rule(self):
        rows = []
        for i in range(3):
            rows += standard_rows(event_id=f"evt{i}")
        out = run(user_dog(max_bets_per_day=2), rows_by_date={DATE: rows},
                  mlb_results={}, game_pk_index={})
        self.assertEqual(out["record"]["bets"], 2)


class TheHouseDrill(unittest.TestCase):
    def setUp(self):
        drill.clear_cache()
        from tests.test_house_pack_hounds import START, basic_stores, mlb_game
        from src.hounds import pack as pack_mod, pack_run
        from src.hounds.learning import champions
        self.stores = basic_stores()
        self.stores.mlb_games.append(mlb_game(900001, "2026-09-20", "NYY", "BOS", 2, 4))      # Boston (home) wins
        self.stores.finalize()
        self.now = START + timedelta(days=2)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds_house_v1.jsonl")
        for p in (mock.patch.object(pack_run, "ledger_path", lambda path=None: path or self.ledger),
                  mock.patch.object(champions, "champion_versions", lambda hs, path: tuple(hs))):
            p.start()
            self.addCleanup(p.stop)
        h = pack_mod.BY_ID["chalk_chihuahua"]
        self.dog = common.Dog(id=h.id, kind=common.KIND_HOUSE, name=h.name, house=h, root_id=h.id)

    def test_a_house_dog_is_replayed_with_the_pack_runner_and_settled(self):
        out = drill.drill(days=7, dog=self.dog, now=self.now, stores=self.stores)
        self.assertEqual(out["record"]["graded"], 1)
        self.assertEqual(out["record"]["wins"], 1)
        self.assertEqual(out["picks"][0]["selection"], "Boston Red Sox ML")
        self.assertAlmostEqual(out["units_average_price"], 0.77, places=2)       # a win at -130
        self.assertEqual(out["label"], "Hindsight drill: not counted")
        self.assertIs(out["counted"], False)
        self.assertEqual(out["dog"]["kind"], "house")
        self.assertFalse(os.path.exists(self.ledger))                              # the real ledger is never touched


if __name__ == "__main__":
    unittest.main()
