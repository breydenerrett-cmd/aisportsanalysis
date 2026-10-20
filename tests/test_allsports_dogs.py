"""Dogs that bet any sport: the menu and ANY, the sport-restricted conditions, the engine over all-sports
rows, the one-pass reader, and the -200 cap on every family. Fixture rows only; no live store is read.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy

from src.hounds import user_engine as eng
from src.hounds import user_rules as R
from src.hounds import user_spec
from src.sports import catalog
from tests import _hounds_rules_fixtures as F
from tests._hounds_user_fixtures import BOOKS, DATE, EVENT, T_LOCK, board_rows, hound, utc

LOCK = utc("2026-10-20T21:10:00Z")


def when(*items, op="all"):
    return {"op": op, "items": list(items)}


def v2_errors(rule_over=None, **top):
    try:
        user_spec.validate_spec(F.v2(rules=[F.rule(**(rule_over or {}))], **top))
    except user_spec.SpecError as exc:
        return exc.errors
    return {}


class TheMenu(unittest.TestCase):
    def test_the_sports_come_from_the_catalog_with_mlb_and_nfl_first(self):
        self.assertEqual(user_spec.SPORTS[:2], ("MLB", "NFL"))
        for code in ("NBA", "NHL", "NCAAF", "NCAAB", "WNBA", "BASKETBALL", "HOCKEY", "SOCCER", "CRICKET",
                     "RUGBY", "AFL"):
            self.assertIn(code, user_spec.SPORTS, code)
        self.assertEqual(user_spec.SPORTS, catalog.dog_families())

    def test_families_with_no_result_source_stay_off_the_dog_menu(self):
        for code in ("BOXING", "OTHER"):
            self.assertNotIn(code, user_spec.SPORTS, code)
            self.assertIn("sports", self._v1_errors(sports=[code]))

    def test_tennis_and_mma_are_on_the_menu_now_that_they_have_a_free_result_source(self):
        for code in ("TENNIS", "MMA"):
            self.assertIn(code, user_spec.SPORTS, code)
            self.assertEqual(self._v1_errors(sports=[code]), {}, code)

    def _v1_errors(self, **over):
        try:
            user_spec.validate_spec({**{"name": "Menu Dog", "tagline": "", "sports": ["MLB"], "markets": ["moneyline"],
                                        "side_rule": "underdog", "price_min": 100, "price_max": 250, "min_books": 3,
                                        "max_bets_per_day": 2, "lock_minutes": 120}, **over})
        except user_spec.SpecError as exc:
            return exc.errors
        return {}

    def test_any_means_every_family_and_is_written_out_explicitly(self):
        spec = user_spec.validate_spec({"name": "Any Dog", "tagline": "", "sports": ["ANY"], "markets": ["moneyline"],
                                        "side_rule": "underdog", "price_min": 100, "price_max": 250, "min_books": 3,
                                        "max_bets_per_day": 2, "lock_minutes": 120})
        self.assertEqual(spec["sports"], list(user_spec.SPORTS))
        self.assertNotIn("ANY", spec["sports"])
        self.assertIn("any sport", user_spec.rule_text(spec))

    def test_any_hashes_like_the_explicit_list_it_expands_to(self):
        base = {"name": "Any Dog", "tagline": "", "markets": ["moneyline"], "side_rule": "underdog",
                "price_min": 100, "price_max": 250, "min_books": 3, "max_bets_per_day": 2, "lock_minutes": 120}
        a = user_spec.validate_spec({**base, "sports": ["ANY"]})
        b = user_spec.validate_spec({**base, "sports": list(user_spec.SPORTS)})
        self.assertEqual(user_spec.spec_hash(a), user_spec.spec_hash(b))

    def test_sports_are_canonically_ordered_and_must_be_distinct(self):
        spec = user_spec.validate_spec({"name": "Order Dog", "tagline": "", "sports": ["SOCCER", "NBA", "MLB"],
                                        "markets": ["moneyline"], "side_rule": "home", "price_min": -150,
                                        "price_max": 250, "min_books": 3, "max_bets_per_day": 2, "lock_minutes": 120})
        self.assertEqual(spec["sports"], ["MLB", "NBA", "SOCCER"])
        self.assertIn("sports", self._v1_errors(sports=["NBA", "NBA"]))
        self.assertIn("sports", self._v1_errors(sports=[]))

    def test_the_menus_offer_any(self):
        self.assertEqual(user_spec.menu()["sports"][-1]["value"], "ANY")
        self.assertEqual(user_spec.builder_menu()["sports"][-1]["value"], "ANY")
        self.assertEqual([s["value"] for s in user_spec.builder_menu()["sports"][:-1]], list(user_spec.SPORTS))

    def test_the_rule_text_names_each_sports_own_start_word(self):
        def text(sports):
            return user_spec.rule_text(user_spec.validate_spec(
                {"name": "Words Dog", "tagline": "", "sports": sports, "markets": ["moneyline"],
                 "side_rule": "underdog", "price_min": 100, "price_max": 250, "min_books": 3,
                 "max_bets_per_day": 2, "lock_minutes": 120}))
        self.assertIn("minutes before tip-off", text(["NBA"]))
        self.assertIn("minutes before kick-off", text(["SOCCER"]))
        self.assertIn("minutes before first pitch or kickoff", text(["MLB", "NFL"]))     # unchanged
        self.assertIn("minutes before first pitch,", text(["MLB"]))
        self.assertIn("minutes before the start", text(["NBA", "SOCCER"]))

    def test_legacy_defaults_stay_mlb_and_nfl(self):
        self.assertEqual(user_spec.LEGACY_SPORTS, ("MLB", "NFL"))


class SportRestrictedConditions(unittest.TestCase):
    def setUp(self):
        self._players = F.patch_players()
        self._players.start()
        self.addCleanup(self._players.stop)

    MLB_NFL_ONLY = (
        {"id": "rest_days"}, {"id": "streak"}, {"id": "last_n_wins"}, {"id": "split_pct"},
        {"id": "head_to_head"}, {"id": "venue_record"}, {"id": "scoring_rate"}, {"id": "league_rank"},
        {"id": "matchup_edge"}, {"id": "team_is", "teams": ["MLB:NYY"]}, {"id": "opponent_is", "teams": ["MLB:NYY"]},
    )

    def test_stat_conditions_that_read_mlb_nfl_tables_are_refused_for_other_sports(self):
        for cond in self.MLB_NFL_ONLY:
            errors = v2_errors({"sports": ["NBA"], "when": when(cond)})
            self.assertTrue(any(cond["id"] in key for key in errors), (cond["id"], errors))
            self.assertTrue(any("MLB / NFL only" in v for v in errors.values()), (cond["id"], errors))

    def test_they_are_refused_in_a_mixed_rule_too(self):
        errors = v2_errors({"sports": ["MLB", "NBA"], "when": when({"id": "rest_days"})})
        self.assertTrue(any("give the other sport its own rule" in v for v in errors.values()), errors)

    def test_they_still_work_for_mlb_and_nfl(self):
        self.assertEqual(v2_errors({"sports": ["MLB", "NFL"], "when": when({"id": "rest_days"})}), {})
        self.assertEqual(v2_errors({"sports": ["NFL"], "when": when({"id": "streak"})}), {})

    def test_mlb_only_conditions_are_refused_for_nfl_and_other_sports(self):
        for cond in ({"id": "temperature"}, {"id": "wind_speed"}, {"id": "roof"}, {"id": "rain_chance"},
                     {"id": "travel_miles"}):
            errors = v2_errors({"sports": ["NHL"], "when": when(cond)})
            self.assertTrue(errors, cond)

    def test_player_props_stay_mlb_only(self):
        errors = v2_errors({"sports": ["NBA"], "markets": ["batter_hits"], "side": "over"})
        self.assertIn("rules[0].sports", errors)
        self.assertEqual(v2_errors({"sports": ["MLB"], "markets": ["batter_hits"], "side": "over"}), {})

    GENERIC = ({"id": "role", "value": "underdog"}, {"id": "steam", "direction": "toward"},
               {"id": "day_of_week", "days": ["sat"]}, {"id": "time_of_day", "value": "night"},
               {"id": "coin_flip", "pct": 50}, {"id": "moon_phase", "value": "full"},
               {"id": "name_letter", "of": "pick", "test": "starts_with", "letter": "S"},
               {"id": "name_length", "of": "pick", "cmp": "gte", "value": 5},
               {"id": "numerology", "value": "closer"})

    def test_generic_rules_work_for_every_family(self):
        for sports in (["NBA"], ["SOCCER"], ["NHL", "CRICKET"], ["ANY"]):
            for cond in self.GENERIC:
                self.assertEqual(v2_errors({"sports": sports, "when": when(cond)}), {}, (sports, cond["id"]))

    def test_spread_size_is_generic_but_spread_only(self):
        self.assertEqual(v2_errors({"sports": ["NBA"], "markets": ["spread"],
                                    "when": when({"id": "spread_size", "cmp": "lte", "value": 7})}), {})
        self.assertTrue(v2_errors({"sports": ["NBA"], "markets": ["moneyline"],
                                   "when": when({"id": "spread_size", "cmp": "lte", "value": 7})}))

    def test_the_builder_menu_lists_generic_conditions_for_every_dog_sport(self):
        by_id = {c["id"]: c for c in R.menu_conditions()}
        self.assertEqual(by_id["role"]["sports"], list(user_spec.SPORTS))
        self.assertEqual(by_id["rest_days"]["sports"], ["MLB", "NFL"])
        self.assertEqual(by_id["temperature"]["sports"], ["MLB"])

    def test_english_parsers_view_of_condition_sports_is_unchanged(self):
        self.assertEqual(set(R.BY_ID["role"].sports), {"MLB", "NFL"})


def family_rows(sport, league, *, home="Boston Celtics", away="New York Knicks", price=(-140, 120), start="2026-10-20T23:10:00Z",
                event_id=EVENT):
    rows = board_rows(T_LOCK, event_id=event_id, home=home, away=away, start=start, sport=sport,
                      moneyline=[(b, price[0], price[1]) for b in BOOKS],
                      spread=(-3.5, [(b, -110, -110) for b in BOOKS]),
                      total=(221.5, [(b, -110, -110) for b in BOOKS]))
    for r in rows:
        r["league"], r["league_title"] = league, league.upper()
    return rows


class TheEngineOnAllSportsRows(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")
        self._players = F.patch_players()
        self._players.start()
        self.addCleanup(self._players.stop)

    def run_day(self, hounds, rows):
        return eng.run(DATE, hounds, rows, ledger=self.ledger, now=LOCK, facts=F.facts())

    def bets(self):
        return [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET]

    def test_a_classic_dog_bets_an_nba_game_and_records_its_league(self):
        self.run_day([hound(sports=["NBA"], markets=["moneyline", "spread", "total"], side_rule="market_moved_toward",
                            price_min=-195, price_max=150)], family_rows("nba", "basketball_nba"))
        # one capture only: no first-board comparison, so a movement rule has nothing to back
        self.assertEqual(self.bets(), [])
        self.run_day([hound("u-dog", sports=["NBA"], side_rule="underdog", price_min=100, price_max=250)],
                     family_rows("nba", "basketball_nba"))
        bet = self.bets()[0]
        self.assertEqual((bet["sport"], bet["league"], bet["league_title"]), ("NBA", "basketball_nba", "BASKETBALL_NBA"))
        self.assertEqual((bet["side"], bet["price"], bet["selection"]), ("away", 120, "New York Knicks to win"))
        self.assertIsNone(bet["game_pk"])

    def test_a_dog_only_bets_the_families_it_chose(self):
        rows = family_rows("nba", "basketball_nba") + family_rows("soccer", "soccer_epl", event_id="soc1",
                                                                    home="Arsenal", away="Chelsea")
        self.run_day([hound(sports=["SOCCER"], side_rule="underdog", price_min=100, price_max=250)], rows)
        self.assertEqual([b["sport"] for b in self.bets()], ["SOCCER"])

    def test_an_any_sport_dog_bets_across_families(self):
        rows = (family_rows("nba", "basketball_nba") + family_rows("soccer", "soccer_epl", event_id="soc1",
                                                                     home="Arsenal", away="Chelsea")
                + family_rows("nhl", "icehockey_nhl", event_id="nhl1", home="Boston Bruins", away="Montreal Canadiens"))
        spec = user_spec.validate_spec(F.v2(rules=[F.rule(sports=["ANY"], side="away", price_min=100, price_max=250,
                                                           when=when({"id": "role", "value": "underdog"}))],
                                            max_bets_per_day=5))
        h = {"id": "u-any", "spec": spec, "spec_hash": user_spec.spec_hash(spec), "created_at": "2026-01-01T00:00:00Z"}
        report = self.run_day([h], rows)
        self.assertEqual(sorted(b["sport"] for b in self.bets()), ["NBA", "NHL", "SOCCER"])
        self.assertEqual(report["bets_written"], 3)

    def test_a_row_of_a_sport_off_the_menu_is_never_a_game(self):
        rows = family_rows("boxing", "boxing_boxing", home="Boxer One", away="Boxer Two")
        games = eng.build_games(rows, near_date=DATE)
        self.assertEqual(games, {})

    def test_a_tennis_row_is_a_game_now_that_tennis_has_a_result_source(self):
        rows = family_rows("tennis", "tennis_wta_wuhan", home="Coco Gauff", away="Iga Swiatek")
        games = eng.build_games(rows, near_date=DATE)
        self.assertEqual(len(games), 1)

    def test_legacy_per_tournament_tennis_rows_are_ignored_too(self):
        rows = family_rows("tennis_wta_wuhan", "tennis_wta_wuhan", home="Coco Gauff", away="Iga Swiatek")
        self.assertEqual(eng.build_games(rows, near_date=DATE), {})


class TheMinus200CapHoldsOnEveryFamily(unittest.TestCase):
    """-1260 favourites are common in tennis; the cap is not a setting for any sport."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")
        self._players = F.patch_players()
        self._players.start()
        self.addCleanup(self._players.stop)

    def run_day(self, hounds, rows):
        return eng.run(DATE, hounds, rows, ledger=self.ledger, now=LOCK, facts=F.facts())

    def bets(self):
        return [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET]

    def heavy(self, sport="soccer", league="soccer_epl"):
        return family_rows(sport, league, price=(-1260, 700), home="Arsenal", away="Chelsea")

    def test_a_band_that_reaches_the_cap_is_refused_at_validation_for_any_sport(self):
        for sports in (["SOCCER"], ["NBA"], ["ANY"]):
            errors = v2_errors({"sports": sports, "price_min": -1300})
            self.assertIn("rules[0].price_min", errors, sports)
            self.assertIn("-200", errors["rules[0].price_min"])

    def test_a_favourite_at_minus_1260_is_never_bet(self):
        spec = user_spec.validate_spec({"name": "Chalk Dog", "tagline": "", "sports": ["SOCCER"],
                                        "markets": ["moneyline"], "side_rule": "favourite", "price_min": -199,
                                        "price_max": 150, "min_books": 3, "max_bets_per_day": 2, "lock_minutes": 120})
        h = {"id": "u-chalk", "spec": spec, "spec_hash": user_spec.spec_hash(spec), "created_at": "2026-01-01T00:00:00Z"}
        report = self.run_day([h], self.heavy())
        self.assertEqual(self.bets(), [])
        self.assertEqual(report["skipped"].get("price_cap"), 1)

    def test_a_hand_edited_spec_with_no_band_floor_still_cannot_make_the_bet(self):
        spec = deepcopy(user_spec.validate_spec(F.v2(rules=[F.rule(sports=["SOCCER"], side="home")])))
        spec["rules"][0]["price_min"] = -5000
        h = {"id": "u-hand", "spec": spec, "spec_hash": "x", "created_at": "2026-01-01T00:00:00Z"}
        report = self.run_day([h], self.heavy())
        self.assertEqual(self.bets(), [])
        self.assertGreaterEqual(report["skipped"].get("price_cap", 0), 1)

    def test_the_long_side_of_a_heavy_favourite_is_fair_game(self):
        spec = user_spec.validate_spec({"name": "Long Dog", "tagline": "", "sports": ["SOCCER"],
                                        "markets": ["moneyline"], "side_rule": "underdog", "price_min": 100,
                                        "price_max": 1000, "min_books": 3, "max_bets_per_day": 2, "lock_minutes": 120})
        h = {"id": "u-long", "spec": spec, "spec_hash": user_spec.spec_hash(spec), "created_at": "2026-01-01T00:00:00Z"}
        self.run_day([h], self.heavy())
        self.assertEqual([(b["side"], b["price"]) for b in self.bets()], [("away", 700)])

    def test_the_cap_guard_is_one_definition(self):
        self.assertTrue(user_spec.beyond_cap(-200))
        self.assertTrue(user_spec.beyond_cap(-1260))
        self.assertFalse(user_spec.beyond_cap(-199))
        self.assertFalse(user_spec.beyond_cap(700))


class TheOnePassReader(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "odds_multibook.jsonl")

    def write(self, rows):
        with open(self.path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, separators=(",", ":")) + "\n")

    def rows(self):
        mlb = board_rows(T_LOCK, moneyline=[("a", -120, 100)])                                  # no sport field
        nba = family_rows("nba", "basketball_nba", event_id="n1")
        soccer = family_rows("soccer", "soccer_epl", event_id="s1", home="Arsenal", away="Chelsea")
        tennis = family_rows("tennis", "tennis_atp", event_id="t1", home="A", away="B")
        old_nba = [dict(r, observed_utc="2026-09-01T10:00:00Z", event_id="old") for r in nba]
        return mlb, nba, soccer, tennis, old_nba

    def test_several_sports_are_read_in_one_pass_with_each_sports_own_window(self):
        mlb, nba, soccer, tennis, old_nba = self.rows()
        self.write(mlb + nba + soccer + tennis + old_nba)
        got = eng.load_rows(DATE, ["MLB", "NFL", "NBA", "SOCCER"], multibook_path=self.path)
        self.assertEqual({r["event_id"] for r in got}, {"evt0001", "n1", "s1"})              # no tennis, no stale rows
        self.assertEqual(len(got), len(mlb) + len(nba) + len(soccer))

    def test_one_pass_and_per_sport_reads_agree(self):
        mlb, nba, soccer, tennis, old_nba = self.rows()
        self.write(mlb + nba + soccer + tennis + old_nba)
        one_pass = eng.load_rows(DATE, ["MLB", "NBA", "SOCCER"], multibook_path=self.path)
        separately = []
        for sport in ("MLB", "NBA", "SOCCER"):
            separately += eng.load_rows(DATE, [sport], multibook_path=self.path)
        key = lambda r: (r["event_id"], r.get("book"), r.get("market") or "", r["observed_utc"])      # noqa: E731
        self.assertEqual(sorted(map(key, one_pass)), sorted(map(key, separately)))

    def test_the_new_families_have_their_own_small_windows(self):
        from src.pipeline import snapshots
        self.assertEqual(snapshots.window_for_date("2026-10-20", "nba"), ("2026-10-16", "2026-10-22"))
        self.assertEqual(snapshots.window_for_date("2026-10-20", "cricket"), ("2026-10-15", "2026-10-22"))
        self.assertEqual(snapshots.window_for_date("2026-10-20", "mlb"), ("2026-10-16", "2026-10-22"))      # unchanged
        self.assertEqual(snapshots.window_for_date("2026-10-20", "nfl"), ("2026-10-04", "2026-10-22"))      # unchanged
        self.assertEqual(snapshots.window_for_date("2026-10-20", "tennis_atp_x"), ("2026-10-16", "2026-10-22"))
        self.assertEqual(snapshots.window_for_date("2026-10-20", "curling"), ("2026-10-04", "2026-10-22"))   # unknown: widest


if __name__ == "__main__":
    unittest.main()
