"""`hounds add-sports`: a member hound gains sports as a NEW VERSION; the old version and its record stay untouched.

The stories this file pins: the old version row is byte-for-byte the same (only retired), a dry run writes nothing, form and
home-cooking conditions are left out (and said) for sports whose data is MLB/NFL-only, MLB props are skipped rather than
renamed, the price band (and so the -200 floor), limits and stake carry, and the result went through validate_spec.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds import add_sports, user_spec, user_store
from src.hounds.interact import feedback_cli

SPEC = {
    "version": 2, "name": "Road Rex", "tagline": "", "color": "ember", "badge": "bone",
    "lock_minutes": 60, "max_bets_per_day": 3, "stake_units": 1.5, "rank_by": "earliest_lock",
    "rules": [
        {"label": "Rested dogs", "sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": 110,
         "price_max": 220, "min_books": 4,
         "when": {"op": "all", "items": [{"id": "role", "value": "underdog"}, {"id": "rest_days", "who": "pick", "cmp": "gte", "value": 2},
                                         {"id": "steam", "direction": "toward"}]}},
        {"label": "Form only", "sports": ["MLB"], "markets": ["moneyline"], "side": "either", "price_min": -150,
         "price_max": 120, "min_books": 3,
         "when": {"op": "all", "items": [{"id": "streak", "who": "pick", "kind": "winning", "value": 3}]}},
        {"label": "Hits", "sports": ["MLB"], "markets": ["batter_hits"], "side": "over", "price_min": -150,
         "price_max": 150, "min_books": 1, "when": None},
    ],
}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"
        p = mock.patch.object(users_store, "db_path", lambda: self.db)
        p.start()
        self.addCleanup(p.stop)
        self.owner = users_store.create_user("rex@example.com", status="active", db=self.db)
        self.hound = user_store.create_hound(self.owner.id, SPEC, db=self.db)

    def rows(self):
        with user_store._connect(self.db) as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM hounds ORDER BY id").fetchall()]


class ThePlan(Base):
    def test_a_dry_run_writes_nothing_and_prints_the_new_rule(self):
        before = self.rows()
        res = add_sports.apply(self.hound["id"], "nba,nhl,nfl,ncaaf", dry_run=True, db=self.db)
        self.assertEqual(self.rows(), before)
        self.assertIsNone(res["new_id"])
        self.assertEqual(res["added"], ["NBA", "NHL", "NFL", "NCAAF"])
        self.assertIn("Paper only", res["sentence"])
        for sport in ("NBA", "NHL", "NFL", "NCAAF"):
            self.assertIn(sport, " ".join(res["spec"]["sports"]))

    def test_a_real_run_makes_a_new_version_and_leaves_the_old_row_as_it_was(self):
        before = {r["id"]: r for r in self.rows()}[self.hound["id"]]
        res = add_sports.apply(self.hound["id"], "nba,nfl", db=self.db)
        after = {r["id"]: r for r in self.rows()}
        old, new = after[self.hound["id"]], after[res["new_id"]]
        for col in ("spec_json", "spec_hash", "created_at", "owner_user_id", "root_id", "version_no"):
            self.assertEqual(old[col], before[col], col)               # the record's rule is untouched
        self.assertEqual(old["status"], "retired")
        self.assertEqual((new["version_of"], new["version_no"], new["root_id"]), (self.hound["id"], 2, old["root_id"]))
        self.assertNotEqual(new["spec_hash"], old["spec_hash"])
        self.assertEqual(json.loads(new["spec_json"])["sports"], ["MLB", "NFL", "NBA"])
        self.assertEqual(len(after), 2)

    def test_limits_stake_name_and_price_band_carry_and_the_floor_holds(self):
        spec = add_sports.apply(self.hound["id"], "nhl", dry_run=True, db=self.db)["spec"]
        self.assertEqual((spec["lock_minutes"], spec["max_bets_per_day"], spec["stake_units"], spec["name"]),
                         (60, 3, 1.5, "Road Rex"))
        for rule in spec["rules"]:
            self.assertGreaterEqual(rule["price_min"], user_spec.SHORTEST_ALLOWED_PRICE)
        nhl = [r for r in spec["rules"] if r["sports"] == ["NHL"] and r["markets"] == ["moneyline"]]
        self.assertEqual((nhl[0]["price_min"], nhl[0]["price_max"], nhl[0]["min_books"]), (110, 220, 4))

    def test_form_conditions_are_dropped_for_sports_without_that_data_and_said(self):
        res = add_sports.apply(self.hound["id"], "ncaaf", dry_run=True, db=self.db)
        text = " ".join(res["notes"])
        self.assertIn("NCAAF: Rested dogs without Days of rest", text)
        self.assertIn("Form only skipped", text)                       # its only condition is MLB/NFL form: it would bet every game
        ncaaf = [r for r in res["spec"]["rules"] if "NCAAF" in r["sports"]]
        self.assertEqual([c["id"] for c in ncaaf[0]["when"]["items"]], ["role", "steam"])

    def test_nfl_keeps_form_conditions_and_joins_the_original_rule(self):
        res = add_sports.apply(self.hound["id"], "nfl", dry_run=True, db=self.db)
        first = res["spec"]["rules"][0]
        self.assertEqual(first["sports"], ["MLB", "NFL"])
        self.assertIn("rest_days", [c["id"] for c in first["when"]["items"]])

    def test_mlb_props_have_no_twin_and_are_skipped_not_renamed(self):
        res = add_sports.apply(self.hound["id"], "nba", dry_run=True, db=self.db)
        self.assertIn("NBA: Hits skipped", " ".join(res["notes"]))
        self.assertFalse([r for r in res["spec"]["rules"] if "NBA" in r["sports"] and r["markets"] == ["batter_hits"]])

    def test_tennis_gets_a_moneyline_only(self):
        res = add_sports.apply(self.hound["id"], "tennis", dry_run=True, db=self.db)
        tennis = [r for r in res["spec"]["rules"] if "TENNIS" in r["sports"]]
        self.assertTrue(tennis)
        self.assertTrue(all(r["markets"] == ["moneyline"] for r in tennis))

    def test_all_means_every_gradable_family_and_reports_the_rest(self):
        res = add_sports.apply(self.hound["id"], "all", dry_run=True, db=self.db)
        self.assertEqual(set(res["added"]) | {"MLB"}, set(user_spec.SPORTS) - {c for c, w in res["skipped"] if "carries" in w})
        skipped = dict(res["skipped"])
        self.assertIn("MLB", skipped)
        self.assertIn("BOXING", skipped)
        self.assertIn("no result source", skipped["BOXING"])
        user_spec.validate_spec(res["raw"])                             # the builder's own normalizer accepts the whole thing

    def test_a_retired_hound_cannot_be_changed_and_nothing_is_written(self):
        add_sports.apply(self.hound["id"], "nba", db=self.db)
        before = self.rows()
        with self.assertRaises(user_store.StoreError):
            add_sports.apply(self.hound["id"], "nhl", db=self.db)
        self.assertEqual(self.rows(), before)

    def test_a_retired_version_names_the_current_one_even_on_a_dry_run(self):
        new_id = add_sports.apply(self.hound["id"], "nba", db=self.db)["new_id"]
        with self.assertRaises(user_store.StoreError) as ctx:
            add_sports.apply(self.hound["id"], "nhl", dry_run=True, db=self.db)
        self.assertIn(f"its current version is {new_id} (v2)", str(ctx.exception))

    def test_all_fills_the_rule_cap_big_leagues_first_and_says_who_had_no_room(self):
        spec = json.loads(json.dumps(SPEC))
        spec["rules"][0]["markets"] = ["moneyline", "spread"]   # each sport keeps a different set: one new rule per set
        spec["name"] = "Wide Rex"
        hound = user_store.create_hound(self.owner.id, spec, db=self.db)
        res = add_sports.apply(hound["id"], "all", dry_run=True, db=self.db)
        self.assertLessEqual(len(res["raw"]["rules"]), add_sports.R.MAX_RULES)
        self.assertEqual(res["added"][0], "NFL")                        # NFL keeps form conditions, so it joins the MLB rules
        room = [c for c, w in res["skipped"] if "no room" in w]
        self.assertTrue(room, res["skipped"])
        self.assertFalse(set(room) & set(res["added"]))
        user_spec.validate_spec(res["raw"])

    def test_refusals(self):
        for text in ("", "mlb", "blah"):
            with self.assertRaises(add_sports.AddSportsError, msg=text):
                add_sports.apply(self.hound["id"], text, dry_run=True, db=self.db)
        with self.assertRaises(add_sports.AddSportsError):
            add_sports.apply("u-nope", "nba", dry_run=True, db=self.db)

    def test_a_classic_v1_hound_is_upgraded_to_rules_then_extended(self):
        v1 = user_store.create_hound(self.owner.id, {"name": "Classic Carl", "tagline": "", "sports": ["MLB"], "markets": ["moneyline"],
                                                     "side_rule": "underdog", "price_min": 100, "price_max": 250, "min_books": 3,
                                                     "max_bets_per_day": 2, "lock_minutes": 120}, db=self.db)
        res = add_sports.apply(v1["id"], "nba", dry_run=True, db=self.db)
        self.assertEqual(res["spec"]["version"], 2)
        self.assertIn("NBA", res["spec"]["sports"])


class TheCommand(Base):
    def run_cmd(self, **kw):
        base = dict(hounds_command="add-sports", id=self.hound["id"], sports="nba", dry_run=False, db=str(self.db))
        base.update(kw)
        lines: list = []
        code = feedback_cli.main(argparse.Namespace(**base), out=lines.append)
        return code, "\n".join(lines)

    def test_dry_run_prints_the_sentence_and_new_run_prints_the_new_id(self):
        code, text = self.run_cmd(dry_run=True)
        self.assertEqual(code, 0, text)
        self.assertIn("DRY RUN", text)
        self.assertIn("rule: ", text)
        self.assertEqual(len(self.rows()), 1)
        code, text = self.run_cmd()
        self.assertEqual(code, 0, text)
        self.assertIn("new version u-", text)
        self.assertEqual(len(self.rows()), 2)

    def test_an_error_exits_2(self):
        self.assertEqual(self.run_cmd(sports="zzz")[0], 2)

    def test_the_parser_accepts_the_documented_flags(self):
        from src import cli
        a = cli.build_parser().parse_args(["hounds", "add-sports", "--id", "u-1", "--sports", "nba,nhl", "--dry-run"])
        self.assertEqual((a.hounds_command, a.sports, a.dry_run), ("add-sports", "nba,nhl", True))


if __name__ == "__main__":
    unittest.main()
