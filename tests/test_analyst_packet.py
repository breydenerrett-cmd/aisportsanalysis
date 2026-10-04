"""The fact packet: deterministic, frozen, honest about holes, and leak-free."""

from __future__ import annotations

import json
import random
import unittest

from src.analyst import packet as P
from tests import analyst_fixtures as F


class ThePacketIsDeterministic(unittest.TestCase):
    def test_same_inputs_same_hash(self):
        self.assertEqual(P.packet_hash(F.build()), P.packet_hash(F.build()))

    def test_row_order_does_not_change_the_hash(self):
        base = P.packet_hash(F.build())
        rng = random.Random(7)
        for _ in range(5):
            rows = F.multibook_rows()
            props = F.batter_prop_rows()
            rng.shuffle(rows)
            rng.shuffle(props)
            self.assertEqual(
                P.packet_hash(F.build(multibook_rows=rows, batter_prop_rows=props)), base)

    def test_ties_at_the_same_instant_are_broken_on_the_rows_not_their_order(self):
        """Two prices from one book at one capture instant (a duplicated or
        re-listed quote) must give one packet whichever row came first."""
        dup_ml = {"observed_utc": F.CAPTURED, "book": "draftkings", "away_team": "New York Yankees",
                  "home_team": "Tampa Bay Rays", "away_price": 120, "home_price": -140}
        dup_prop = {"observed_utc": F.CAPTURED, "book": "draftkings", "market": "batter_hits",
                    "player": "Junior Caminero", "line": "0.5", "side": "Over", "price": -250}
        dup_tt = {"observed_utc": F.CAPTURED, "book": "draftkings", "market": "team_totals",
                  "team": "New York Yankees", "line": "4.5", "side": "Over", "price": 105}
        hashes = set()
        for order in range(4):
            rows = F.multibook_rows() + [dup_ml]
            props = F.batter_prop_rows() + [dup_prop]
            tt = F.team_total_rows() + [dup_tt]
            if order % 2:
                rows.reverse()
                props.reverse()
            if order > 1:
                tt.reverse()
            hashes.add(P.packet_hash(F.build(multibook_rows=rows, batter_prop_rows=props,
                                             team_total_rows=tt)))
        self.assertEqual(len(hashes), 1)

    def test_a_different_input_changes_the_hash(self):
        self.assertNotEqual(P.packet_hash(F.build()),
                            P.packet_hash(F.build(multibook_rows=F.multibook_rows(home_ml=(-140, -127, -132)))))

    def test_the_packet_survives_a_json_round_trip_unchanged(self):
        packet = F.build()
        again = json.loads(json.dumps(packet))
        self.assertEqual(P.packet_hash(again), P.packet_hash(packet))

    def test_it_reads_no_clock(self):
        # built_at is the only time in it, and it is what the caller passed
        self.assertEqual(F.build(built_at="2026-10-03T18:00:00Z")["built_at"], "2026-10-03T18:00:00Z")
        with self.assertRaises(ValueError):
            P.build_packet(F.payload(), built_at="not a time")


class NothingFromTheFutureReachesIt(unittest.TestCase):
    def test_final_scores_never_enter_the_game_block(self):
        packet = F.build(with_scores=True, state="pending")
        text = json.dumps(packet)
        for leaked in ("away_score", "home_score", "winner", "total_runs", "first_five"):
            self.assertNotIn(leaked, text)
        self.assertEqual(sorted(packet["game"]), sorted([
            "game_id", "game_pk", "date", "away", "home", "venue", "first_pitch_utc",
            "state", "detailed_state", "game_type", "probables"]))

    def test_a_quote_captured_after_the_build_is_dropped(self):
        rows = F.multibook_rows()
        rows.append({"observed_utc": "2026-10-03T19:00:00+00:00", "book": "latebook",
                     "away_team": "New York Yankees", "home_team": "Tampa Bay Rays",
                     "away_price": 300, "home_price": -400})
        books = {q["book"] for o in F.build(multibook_rows=rows)["markets"]["moneyline"]["options"]
                 for q in o["quotes"]}
        self.assertNotIn("latebook", books)

    def test_a_quote_captured_after_first_pitch_is_dropped_even_if_before_the_build(self):
        rows = F.multibook_rows()
        rows.append({"observed_utc": "2026-10-03T22:45:00+00:00", "book": "inplay",
                     "away_team": "New York Yankees", "home_team": "Tampa Bay Rays",
                     "away_price": 300, "home_price": -400})
        packet = F.build(multibook_rows=rows, built_at="2026-10-03T23:00:00Z")
        books = {q["book"] for o in packet["markets"]["moneyline"]["options"] for q in o["quotes"]}
        self.assertNotIn("inplay", books)

    def test_the_newest_pregame_quote_per_book_wins(self):
        rows = F.multibook_rows()
        rows.append({"observed_utc": "2026-10-03T17:30:00+00:00", "book": "draftkings",
                     "away_team": "New York Yankees", "home_team": "Tampa Bay Rays",
                     "away_price": 125, "home_price": -150})
        opt = next(o for o in F.build(multibook_rows=rows)["markets"]["moneyline"]["options"]
                   if o["selection"] == "TB")
        dk = next(q for q in opt["quotes"] if q["book"] == "draftkings")
        self.assertEqual(dk["price"], -150)

    def test_an_undated_quote_is_dropped(self):
        rows = F.multibook_rows()
        rows.append({"book": "nodate", "away_team": "x", "home_team": "y",
                     "away_price": 100, "home_price": -110})
        books = {q["book"] for o in F.build(multibook_rows=rows)["markets"]["moneyline"]["options"]
                 for q in o["quotes"]}
        self.assertNotIn("nodate", books)


class EveryPriceCarriesItsBookAndCaptureTime(unittest.TestCase):
    def test_every_quote_has_a_book_a_price_and_a_capture_time(self):
        packet = F.build()
        for slot_id, market in packet["markets"].items():
            for opt in market["options"]:
                self.assertTrue(opt["quotes"], slot_id)
                for q in opt["quotes"]:
                    self.assertEqual(set(q), {"book", "price", "captured_utc"})
                    self.assertTrue(q["captured_utc"].endswith("Z"))
                    self.assertGreaterEqual(abs(q["price"]), 100)

    def test_slots_are_the_markets_in_a_fixed_order(self):
        packet = F.build()
        self.assertEqual([s["slot_id"] for s in packet["slots"]][:5],
                         ["moneyline", "run_line", "total", "team_total_away", "team_total_home"])
        self.assertTrue(all(s["slot_id"].startswith("prop_") for s in packet["slots"][5:]))
        self.assertEqual(list(packet["markets"]), [s["slot_id"] for s in packet["slots"]])

    def test_the_lean_is_first_and_is_the_side_the_books_favour(self):
        ml = F.build()["markets"]["moneyline"]
        self.assertEqual(ml["lean"], "TB")
        self.assertEqual(ml["options"][0]["selection"], "TB")
        self.assertGreater(ml["options"][0]["fair_probability"], ml["options"][1]["fair_probability"])

    def test_run_line_selections_name_the_line_from_each_sides_view(self):
        rl = F.build()["markets"]["run_line"]
        self.assertEqual(sorted(o["selection"] for o in rl["options"]), ["NYY +1.5", "TB -1.5"])

    def test_a_one_sided_prop_has_one_option_and_no_other_side(self):
        hr = next(m for m in F.build()["markets"].values()
                  if m["market"] == "prop" and m["context"]["stat"] == "batter_home_runs")
        self.assertEqual(len(hr["options"]), 1)
        self.assertIsNone(hr["options"][0]["fair_probability"])

    def test_prop_context_carries_the_repo_models_numbers_when_a_board_exists(self):
        caminero = next(m for m in F.build()["markets"].values()
                        if m["market"] == "prop" and m["context"]["player"] == "Junior Caminero")
        self.assertEqual(caminero["context"]["repo_model_probability"], 0.7636)
        self.assertEqual(caminero["context"]["season_games"], 27)

    def test_the_prop_cap_is_respected_and_the_rest_are_counted_in_missing(self):
        cfg = dict(F.CFG, max_props_per_game=2)
        packet = F.build(cfg=cfg)
        props = [m for m in packet["markets"].values() if m["market"] == "prop"]
        self.assertEqual(len(props), 2)
        thin = [m for m in packet["missing"] if m["item"] == "props"]
        self.assertEqual(len(thin), 1)
        self.assertEqual(thin[0]["reason"], "4 player props were priced and 2 analyzed: "
                                            "2 were left out by the limit of 2 props per game")

    def test_starting_pitcher_strikeouts_are_always_analyzed_first(self):
        cfg = dict(F.CFG, max_props_per_game=1)
        packet = F.build(cfg=cfg)
        only = [m for m in packet["markets"].values() if m["market"] == "prop"]
        self.assertEqual(only[0]["context"]["stat"], "pitcher_strikeouts")


class TheMissingListIsHonest(unittest.TestCase):
    def items(self, packet):
        return {(m["item"], m["kind"]) for m in packet["missing"]}

    def test_the_payloads_own_gaps_are_listed_verbatim(self):
        packet = F.build()
        got = {m["item"]: m["reason"] for m in packet["missing"] if m["kind"] == "absent"}
        self.assertEqual(got["lineups"], "lineup not posted yet, or not fetched")

    def test_a_missing_market_is_listed_as_absent_not_invented(self):
        packet = F.build(team_total_rows=[])
        self.assertNotIn("team_total_away", packet["markets"])
        self.assertIn(("team_totals", "absent"), self.items(packet))

    def test_no_prices_at_all_leaves_no_markets_and_says_so(self):
        packet = F.build(multibook_rows=[], team_total_rows=[], batter_prop_rows=[],
                         pitcher_prop_rows=[], prop_board=[])
        self.assertEqual(packet["markets"], {})
        self.assertEqual(packet["slots"], [])
        for item in ("moneyline", "run_line", "total", "props"):
            self.assertIn((item, "absent"), self.items(packet))

    def test_a_stale_quote_is_flagged_stale(self):
        packet = F.build(built_at="2026-10-03T21:00:00Z")
        self.assertIn(("moneyline", "stale"), self.items(packet))

    def test_team_and_starter_stats_that_stop_days_before_the_game_are_flagged_stale(self):
        packet = F.build(section_as_of={"teams": "2026-09-23", "starters": "2026-10-02"})
        self.assertIn(("teams", "stale"), self.items(packet))
        self.assertNotIn(("starters", "stale"), self.items(packet))
        reason = next(m["reason"] for m in packet["missing"] if m["item"] == "teams" and m["kind"] == "stale")
        self.assertIn("run only through 2026-09-23, 10 days before the game", reason)
        # yesterday's stats are current
        self.assertNotIn(("teams", "stale"), self.items(F.build()))

    def test_a_section_stamped_long_before_the_game_is_flagged_stale(self):
        self.assertIn(("splits", "stale"), self.items(F.build()))

    def test_an_empty_bullpen_is_absent_not_zero_workload(self):
        payload = F.payload()
        payload["advanced"]["sections"]["bullpen"] = {
            "NYY": {"team": "NYY", "relievers": [], "total_innings": 0},
            "TB": {"team": "TB", "relievers": [], "total_innings": 0}}
        packet = P.build_packet(payload, built_at=F.BUILT_AT, multibook_rows=F.multibook_rows(), cfg=F.CFG)
        self.assertIn(("bullpen", "absent"), self.items(packet))

    def test_limits_are_stated(self):
        self.assertTrue(any("alternate" in s for s in F.build()["limits"]))


class SectionsAreSafeToCiteByPath(unittest.TestCase):
    def test_market_sections_are_rebuilt_not_copied(self):
        sections = F.build()["sections"]
        self.assertNotIn("price_improvement", sections)
        self.assertNotIn("market", sections)

    def test_identifier_and_coordinate_keys_are_dropped(self):
        park = F.build()["sections"]["park"]["values"]
        self.assertNotIn("lat", park)
        self.assertNotIn("lon", park)

    def test_every_key_in_the_packet_is_path_safe(self):
        for path, _ in P.iter_leaves(F.build()):
            self.assertRegex(path, P._PATH_RE.pattern, path)

    def test_awkward_source_keys_become_path_safe(self):
        splits = F.build()["sections"]["splits"]["values"]
        self.assertIn("Away_Games", json.dumps(splits))
        self.assertNotIn("Away Games", json.dumps(splits))

    def test_every_section_says_when_it_is_as_of(self):
        for name, section in F.build()["sections"].items():
            self.assertTrue(section["as_of"], name)
            self.assertTrue(section["as_of_basis"], name)
        self.assertEqual(F.build()["sections"]["teams"]["as_of"], "2026-10-02")

    def test_the_read_key_is_included_when_present_and_absent_when_not(self):
        payload = F.payload()
        self.assertNotIn("read", P.build_packet(payload, built_at=F.BUILT_AT, cfg=F.CFG)["sections"])
        payload["read"] = {"lean": "home", "reasons": ["a stored reason"]}
        packet = P.build_packet(payload, built_at=F.BUILT_AT, cfg=F.CFG)
        self.assertEqual(packet["sections"]["read"]["values"]["lean"], "home")


class ThePathGrammar(unittest.TestCase):
    def setUp(self):
        self.packet = F.build()

    def test_a_good_path_resolves(self):
        ok, value = P.resolve_path(self.packet, "markets.moneyline.options[0].best.price")
        self.assertTrue(ok)
        self.assertEqual(value, -127)
        ok, value = P.resolve_path(self.packet, "sections.starters.values.home_sp_era")
        self.assertEqual((ok, value), (True, 2.8761))

    def test_the_data_prefix_mistake_is_named(self):
        """The benchmark critic wrote data.best_price for 102 facts."""
        ok, reason = P.resolve_path(self.packet, "data.best_price")
        self.assertFalse(ok)
        self.assertIn("start at the packet's own top-level key", reason)

    def test_bad_paths_say_why(self):
        for path, fragment in (("markets.nope", "no key 'nope'"),
                               ("markets.moneyline.options[9]", "no list item [9]"),
                               ("", "empty"), ("markets..x", "not a valid path"),
                               ("markets.moneyline.options.0", "not a valid path"),
                               ("markets['moneyline']", "not a valid path")):
            ok, reason = P.resolve_path(self.packet, path)
            self.assertFalse(ok, path)
            self.assertIn(fragment, reason)

    def test_a_non_string_path_is_refused(self):
        self.assertFalse(P.resolve_path(self.packet, None)[0])
        self.assertFalse(P.resolve_path(self.packet, 5)[0])

    def test_the_numbers_pool_holds_numbers_and_not_bools(self):
        nums = P.numbers_in_packet({"a": 1, "b": True, "c": 2.5, "d": "x", "e": [3]})
        self.assertEqual(sorted(nums), [1, 2.5, 3])


if __name__ == "__main__":
    unittest.main()
