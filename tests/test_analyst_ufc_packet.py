"""The UFC fight packet: determinism, slots, the holes, and above all NO LEAKAGE.

Every store is the data layer's synthetic world in a temporary directory
(tests/ufc_analyst_fixtures.py); nothing reads the repo's real data. The leakage tests are
the point of this file: a result, a later bout, a post-start price, a price from the live
in-play feed, and the fight's own statistics must never reach the model, and each is proved
by building the packet from a world that contains the leak and from one that does not and
comparing them.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from src.analyst import packet as base
from src.analyst import ufc_packet
from src.ledger.chain import canonical_bytes
from tests import ufc_analyst_fixtures as F
from tests.test_datasvc_ufc_features import FETCHED, SOURCE, build_store, odds_row

SLOTS = ["moneyline", "rounds_total", "method_a_ko", "method_a_sub", "method_a_dec",
         "method_b_ko", "method_b_sub", "method_b_dec"]
RESULT_KEYS = {"winner_id", "result_method", "result_method_raw", "result_detail", "result_target",
               "end_round", "end_time_s", "fight_time_s", "winner"}


class World(unittest.TestCase):
    """A fresh store per test: the tests change it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = F.make_store(self.root)

    def packet(self, **kw):
        return F.packet(self.store, **kw)

    def odds_world(self, *rows, name="odds"):
        sub = self.root / name
        return F.make_store(sub, rows=list(rows))


class TheShape(World):
    def test_top_level_keys_and_version(self):
        p = self.packet()
        self.assertEqual(set(p), {"packet_version", "built_at", "bout", "figure_units", "sections",
                                  "markets", "slots", "missing", "limits", "how_to_read"})
        self.assertEqual(p["packet_version"], "analyst_ufc_packet_v1")
        self.assertEqual(p["built_at"], "2026-10-10T16:00:00Z")

    def test_the_slots_are_every_priced_market_in_a_fixed_order(self):
        p = self.packet()
        self.assertEqual([s["slot_id"] for s in p["slots"]], SLOTS)
        self.assertEqual(list(p["markets"]), SLOTS)
        self.assertEqual({s["slot_id"]: s["market"] for s in p["slots"]},
                         {"moneyline": "moneyline", "rounds_total": "rounds_total",
                          **{k: "method" for k in SLOTS[2:]}})

    def test_a_slot_lists_its_selections_lean_first(self):
        slots = {s["slot_id"]: s for s in self.packet()["slots"]}
        self.assertEqual(slots["moneyline"]["selections"], [F.A, F.B])
        self.assertEqual(slots["rounds_total"]["selections"], ["Over 4.5", "Under 4.5"])
        self.assertEqual(slots["method_a_ko"]["selections"], ["Alex Archer by KO/TKO/DQ"])

    def test_the_bout_block_is_the_identity_and_nothing_else(self):
        bout = self.packet()["bout"]
        self.assertEqual(bout["bout_id"], F.BOUT)
        self.assertEqual((bout["event_id"], bout["date"], bout["state"]), (F.EVENT, F.DATE, "scheduled"))
        self.assertEqual(bout["start_utc"], F.START_ISO)
        self.assertEqual((bout["weight_class"], bout["scheduled_rounds"], bout["round_minutes"]),
                         ("Welterweight", 5, 5))
        self.assertEqual(bout["fighter_a"], {"id": "101", "name": F.A, "name_known": True})
        self.assertEqual(bout["fighter_b"], {"id": "102", "name": F.B, "name_known": True})
        self.assertFalse(RESULT_KEYS & set(bout))

    def test_it_is_plain_json_with_no_nan(self):
        p = self.packet()
        self.assertEqual(json.loads(json.dumps(p, allow_nan=False)), p)

    def test_every_key_is_path_safe_and_every_leaf_path_resolves(self):
        p = self.packet()
        key = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

        def keys(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield k
                    yield from keys(v)
            elif isinstance(node, list):
                for v in node:
                    yield from keys(v)
        self.assertEqual([k for k in keys(p) if not key.match(k)], [])
        leaves = list(base.iter_leaves(p))
        self.assertGreater(len(leaves), 300)
        for path, value in leaves:
            ok, found = base.resolve_path(p, path)
            self.assertTrue(ok, f"{path}: {found}")
            self.assertEqual(found, value)

    def test_no_identifier_reaches_a_fighter_section(self):
        blob = json.dumps(self.packet()["sections"])
        for marker in ("fighter_id", "opponent_id", "bout_id", "winner_id", "source_url"):
            self.assertNotIn(marker, blob)

    def test_how_to_read_says_which_side_is_a_and_which_way_a_difference_points(self):
        text = " ".join(self.packet()["how_to_read"])
        self.assertIn("a is bout.fighter_a and b is bout.fighter_b", text)
        self.assertIn("A difference is a minus b", text)
        self.assertIn("previous_meetings are written from fighter a's side", text)
        diffs = self.packet()["sections"]["matchup"]["values"]["differentials"]
        d = diffs["sig_strikes_landed_per_min"]
        self.assertEqual(d["diff"], round(d["a"] - d["b"], 4))          # the claim it makes is true

    def test_the_units_of_every_figure_are_listed_once(self):
        p = self.packet()
        self.assertEqual(p["figure_units"]["finish_rate"], "finishing wins (KO/TKO or submission) per fight")
        figures = set(p["sections"]["fighter_a"]["values"]["figures"])
        self.assertTrue(figures <= set(p["figure_units"]))
        blob = json.dumps(p["sections"]["fighter_a"])
        self.assertNotIn("significant strikes landed per minute", blob)   # not repeated per figure


class TheMarkets(World):
    def test_the_moneyline_is_each_fighter_with_the_favourite_first(self):
        m = self.packet()["markets"]["moneyline"]
        self.assertEqual((m["lean"], len(m["options"])), (F.A, 2))
        a, b = m["options"]
        self.assertEqual((a["selection"], a["side"], a["best"]), (F.A, "a", {"price": -170, "book": "DraftKings"}))
        self.assertEqual((b["selection"], b["side"], b["best"]), (F.B, "b", {"price": 145, "book": "DraftKings"}))
        self.assertEqual(a["quotes"], [{"book": "DraftKings", "price": -170, "captured_utc": F.ODDS_FETCHED}])
        self.assertEqual((a["fair_probability"], b["fair_probability"]), (0.6067, 0.3933))
        self.assertEqual((a["implied_probability"], b["implied_probability"]), (0.6296, 0.4082))
        self.assertEqual((a["open_price"], b["open_price"]), (-150, 130))
        self.assertEqual(m["as_of"], F.ODDS_FETCHED)

    def test_the_lean_follows_the_price_not_the_side(self):
        """Fighter a is the underdog here: the lean flips and every price stays on its fighter."""
        store = self.odds_world(F.odds(a_ml_current=145, a_ml_open=130, b_ml_current=-170, b_ml_open=-150))
        m = F.packet(store)["markets"]["moneyline"]
        self.assertEqual(m["lean"], F.B)
        self.assertEqual([(o["selection"], o["best"]["price"]) for o in m["options"]],
                         [(F.B, -170), (F.A, 145)])

    def test_the_moneyline_needs_both_sides(self):
        store = self.odds_world(F.odds(b_ml_current=None))
        p = F.packet(store)
        self.assertNotIn("moneyline", p["markets"])
        self.assertIn("moneyline", {m["item"] for m in p["missing"]})
        self.assertIn("rounds_total", p["markets"])          # the other markets are unaffected

    def test_the_rounds_total_is_over_and_under_the_current_line(self):
        m = self.packet()["markets"]["rounds_total"]
        over, under = m["options"]
        self.assertEqual((over["selection"], over["side"], over["line"]), ("Over 4.5", "over", 4.5))
        self.assertEqual((under["selection"], under["best"]["price"]), ("Under 4.5", -110))
        self.assertEqual((over["fair_probability"], under["fair_probability"]), (0.5, 0.5))
        self.assertEqual((over["open_price"], over["open_line"]), (-120, 4.5))
        self.assertEqual(under["open_price"], 100)

    def test_a_moved_line_shows_both_lines_and_the_current_prices_are_the_current_lines(self):
        store = self.odds_world(F.odds(rounds_total=3.5, rounds_total_current=3.5, rounds_total_open=4.5,
                                       over_current=-140, under_current=120))
        over, under = F.packet(store)["markets"]["rounds_total"]["options"]
        self.assertEqual((over["selection"], over["line"], over["open_line"]), ("Over 3.5", 3.5, 4.5))
        self.assertEqual((over["best"]["price"], under["best"]["price"]), (-140, 120))

    def test_a_row_with_no_current_line_has_no_rounds_total(self):
        store = self.odds_world(F.odds(rounds_total_current=None))
        p = F.packet(store)
        self.assertNotIn("rounds_total", p["markets"])
        self.assertIn(("rounds_total", "absent"), {(m["item"], m["kind"]) for m in p["missing"]})

    def test_a_row_from_before_the_per_phase_fields_uses_its_one_line(self):
        row = F.odds()
        for key in ("rounds_total_current", "rounds_total_open", "rounds_total_close"):
            del row[key]
        over = F.packet(self.odds_world(row))["markets"]["rounds_total"]["options"][0]
        self.assertEqual(over["line"], 4.5)
        self.assertNotIn("open_line", over)             # an open line it never recorded is not guessed

    def test_the_rounds_total_needs_both_prices(self):
        p = F.packet(self.odds_world(F.odds(under_current=None)))
        self.assertNotIn("rounds_total", p["markets"])

    def test_each_method_is_a_one_option_slot_for_one_fighter(self):
        markets = self.packet()["markets"]
        expected = {
            "method_a_ko": ("Alex Archer by KO/TKO/DQ", "a", "ko_tko_dq", 280, 300),
            "method_a_sub": ("Alex Archer by submission", "a", "submission", 750, 800),
            "method_a_dec": ("Alex Archer by decision", "a", "decision", 330, 350),
            "method_b_ko": ("Ben Brawler by KO/TKO/DQ", "b", "ko_tko_dq", 420, 450),
            "method_b_sub": ("Ben Brawler by submission", "b", "submission", 850, 900),
            "method_b_dec": ("Ben Brawler by decision", "b", "decision", 380, 400),
        }
        for slot_id, (selection, side, method, price, open_price) in expected.items():
            m = markets[slot_id]
            self.assertEqual(m["market"], "method")
            self.assertEqual(len(m["options"]), 1, slot_id)
            opt = m["options"][0]
            self.assertEqual((opt["selection"], opt["side"], opt["best"]["price"], opt["open_price"]),
                             (selection, side, price, open_price), slot_id)
            self.assertEqual(m["lean"], selection)
            self.assertEqual(m["context"], {"fighter_side": side, "method": method})
            self.assertIsNotNone(opt["fair_probability"])

    def test_the_method_probabilities_are_one_margin_over_all_six_outcomes(self):
        markets = self.packet()["markets"]
        fair = sum(markets[s]["options"][0]["fair_probability"] for s in SLOTS[2:])
        self.assertAlmostEqual(fair, 1.0, places=2)
        implied = sum(markets[s]["options"][0]["implied_probability"] for s in SLOTS[2:])
        self.assertGreater(implied, 1.05)                   # the margin is still in the implied ones

    def test_a_method_price_that_is_not_quoted_has_no_slot_and_no_margin_free_number(self):
        mo = F.method_odds()
        mo["b"]["submission"]["current"] = None
        p = F.packet(self.odds_world(F.odds(method_odds=mo)))
        self.assertNotIn("method_b_sub", p["markets"])
        self.assertEqual(len([s for s in p["slots"] if s["market"] == "method"]), 5)
        for slot_id in ("method_a_ko", "method_b_dec"):
            self.assertIsNone(p["markets"][slot_id]["options"][0]["fair_probability"])
            self.assertIsNotNone(p["markets"][slot_id]["options"][0]["implied_probability"])
        self.assertIn(("method", "thin"), {(m["item"], m["kind"]) for m in p["missing"]})

    def test_open_only_method_prices_are_not_a_current_price(self):
        """The data layer's own fixture row has method prices for `open` only."""
        p = F.packet(self.odds_world(odds_row(fetched_utc=F.ODDS_FETCHED)))
        self.assertFalse([s for s in p["slots"] if s["market"] == "method"])
        self.assertIn(("method", "absent"), {(m["item"], m["kind"]) for m in p["missing"]})
        self.assertIn("moneyline", p["markets"])

    def test_the_book_is_the_provider_and_prices_are_the_current_quote(self):
        for market in self.packet()["markets"].values():
            for opt in market["options"]:
                self.assertEqual([q["book"] for q in opt["quotes"]], ["DraftKings"])
                self.assertEqual(opt["quotes"][0]["captured_utc"], F.ODDS_FETCHED)
                self.assertEqual(opt["books"], 1)

    def test_a_row_whose_sides_cannot_be_matched_to_the_fighters_shows_no_price(self):
        p = F.packet(self.odds_world(F.odds(orientation="unknown")))
        self.assertEqual(p["markets"], {})
        self.assertEqual(p["slots"], [])
        why = next(m for m in p["missing"] if m["item"] == "odds")
        self.assertIn("withheld", why["reason"])


class Determinism(World):
    def test_the_same_inputs_give_the_same_packet_and_hash(self):
        a, b = self.packet(), self.packet()
        self.assertEqual(a, b)
        self.assertEqual(base.packet_hash(a), base.packet_hash(b))
        self.assertEqual(canonical_bytes(a), canonical_bytes(b))

    def test_a_second_store_built_the_same_way_gives_the_same_hash(self):
        other = F.make_store(self.root / "again")
        self.assertEqual(base.packet_hash(self.packet()), base.packet_hash(F.packet(other)))

    def test_the_order_of_the_odds_rows_cannot_change_the_hash(self):
        extra = F.odds(provider_id="200", provider="Other Book", a_ml_current=-300, b_ml_current=250)
        one = F.packet(self.odds_world(F.odds(), extra, name="one"))
        two = F.packet(self.odds_world(extra, F.odds(), name="two"))
        self.assertEqual(base.packet_hash(one), base.packet_hash(two))

    def test_it_reads_no_clock(self):
        self.assertEqual(base.packet_hash(self.packet()),
                         base.packet_hash(self.packet()))
        later = self.packet(built_at="2026-10-10T16:30:00Z")
        self.assertEqual(later["built_at"], "2026-10-10T16:30:00Z")
        self.assertEqual(later["sections"], self.packet()["sections"])

    def test_a_bad_built_at_is_a_value_error(self):
        with self.assertRaises(ValueError):
            self.packet(built_at="soon")

    def test_a_bout_that_is_not_there_or_has_no_two_fighters_is_refused(self):
        with self.assertRaises(ufc_packet.UfcPacketError):
            self.packet(bout_id="nope")
        bout = dict(self.store.bout_by_id()[F.BOUT], fighter_b_id=None)
        self.store.upsert("bouts", [bout])
        with self.assertRaises(ufc_packet.UfcPacketError):
            self.packet()


class NoLeakage(World):
    """The most important tests in this file."""

    def test_the_bouts_own_result_never_enters(self):
        clean = self.packet()
        finished = F.finish_the_bout(self.store)
        self.store.upsert("fight_stats", [{
            "bout_id": F.BOUT, "fighter_id": "101", "opponent_id": "102", "event_id": F.EVENT,
            "date_utc": F.START, "sig_strikes_landed": 987654, "sig_strikes_attempted": 987999,
            "knock_downs": 7, "stats_complete": True, "source_url": SOURCE, "fetched_utc": FETCHED}])
        leaky = self.packet()
        self.assertEqual(leaky["sections"], clean["sections"])
        self.assertEqual({k: v for k, v in leaky["bout"].items() if k != "state"},
                         {k: v for k, v in clean["bout"].items() if k != "state"})
        blob = json.dumps(leaky)
        for marker in ("ElbowsMarker", "ko-marker", "987654", "987999"):
            self.assertNotIn(marker, blob)
        self.assertFalse(RESULT_KEYS & set(leaky["bout"]))
        self.assertEqual(finished["status"], "final")

    def test_a_later_bout_between_the_same_two_never_enters(self):
        clean = self.packet()
        base_bout = dict(self.store.bout_by_id()[F.BOUT])
        self.store.upsert("bouts", [dict(
            base_bout, bout_id="9300", event_id="7300", date_utc="2026-12-05T22:00Z", status="final",
            winner_id="102", result_method="SUB", result_method_raw="sub", result_detail="FutureMarker",
            end_round=1, end_time_s=61.0, fight_time_s=61.0, match_number=1)])
        self.store.upsert("events", [{
            "event_id": "7300", "name": "Synthetic Rematch Night", "short_name": "SRN", "date_utc": "2026-12-05T22:00Z",
            "season": 2026, "status": "final", "venue_id": None, "bout_ids": ["9300"],
            "source_url": SOURCE, "fetched_utc": FETCHED}])
        leaky = self.packet()
        self.assertEqual(leaky["sections"], clean["sections"])
        self.assertEqual(leaky["sections"]["matchup"]["values"]["previous_meetings"][0]["date_utc"],
                         "2026-03-14T22:00Z")        # the rematch that already happened, and only that
        self.assertNotIn("FutureMarker", json.dumps(leaky))

    def test_the_packet_equals_the_packet_from_a_world_that_ends_at_the_bouts_start(self):
        """Built from the full store (the bout finished, later bouts present) and from the
        store as it was (everything from the start on deleted, the bout still scheduled)."""
        full = build_store(self.root / "full", odds=[])
        for bout_id in ("9009", "9011"):
            bout = full.bout_by_id()[bout_id]
            start = bout["date_utc"]
            past = build_store(self.root / f"past_{bout_id}", before=start, odds=[])
            past.upsert("bouts", [dict(bout, status="scheduled", winner_id=None, result_method=None,
                                       result_method_raw=None, result_detail=None, end_round=None,
                                       end_time_s=None, fight_time_s=None)])
            past.upsert("events", [full.event_by_id()[bout["event_id"]]])
            at = "2026-06-10T12:00:00Z"
            real = F.packet(full, bout_id=bout_id, built_at=at)
            then = F.packet(past, bout_id=bout_id, built_at=at)
            self.assertEqual(real["sections"], then["sections"], f"{bout_id}: the future leaked in")
            self.assertEqual({k: v for k, v in real["bout"].items() if k != "state"},
                             {k: v for k, v in then["bout"].items() if k != "state"})
            self.assertEqual(real["missing"], then["missing"])

    def test_a_price_fetched_before_the_start_and_the_build_is_used(self):
        self.assertEqual(len(self.packet()["markets"]), 8)

    def test_a_price_fetched_after_the_build_is_not(self):
        later = self.odds_world(F.odds(fetched_utc="2026-10-10T16:30:00Z"))
        p = F.packet(later)
        self.assertEqual((p["markets"], p["slots"]), ({}, []))
        why = next(m for m in p["missing"] if m["item"] == "odds")
        self.assertIn("after this packet was built", why["reason"])

    def test_a_price_fetched_at_the_start_is_not(self):
        store = self.odds_world(F.odds(fetched_utc=F.START_ISO))
        p = F.packet(store, built_at="2026-10-10T23:30:00Z")
        self.assertEqual(p["markets"], {})
        why = next(m for m in p["missing"] if m["item"] == "odds")
        self.assertIn("at or after the bout's scheduled start", why["reason"])

    def test_a_price_fetched_after_the_start_is_not_even_when_the_packet_is_built_later(self):
        store = self.odds_world(F.odds(fetched_utc="2026-10-11T01:00:00Z", is_closing=True))
        p = F.packet(store, built_at="2026-10-11T02:00:00Z")
        self.assertEqual(p["markets"], {})

    def test_the_closing_line_of_a_finished_bout_is_not_a_pre_fight_price(self):
        """Even if its capture time were wrong, a row flagged as the closing line is refused."""
        store = self.odds_world(F.odds(is_closing=True))
        p = F.packet(store)
        self.assertEqual(p["markets"], {})
        self.assertIn("after the bout was over", next(m for m in p["missing"] if m["item"] == "odds")["reason"])

    def test_a_price_that_cannot_be_dated_is_not_shown(self):
        for stamp in (None, "", "yesterday"):
            store = self.odds_world(F.odds(fetched_utc=stamp), name=f"d{abs(hash(stamp))}")
            p = F.packet(store)
            self.assertEqual(p["markets"], {}, stamp)
            self.assertIn("cannot be shown to precede", next(m for m in p["missing"] if m["item"] == "odds")["reason"])

    def test_the_live_in_play_feed_is_never_used_even_alone(self):
        live = F.odds(provider_id="59", provider="ESPN Bet - Live Odds", in_play=True,
                      a_ml_current=-27501, b_ml_current=15003, over_current=-19997, under_current=11117,
                      a_ml_open=-27501, b_ml_open=15003)
        only = F.packet(self.odds_world(live, name="only"))
        self.assertEqual(only["markets"], {})
        self.assertIn("in-fight", next(m for m in only["missing"] if m["item"] == "odds")["reason"])
        both = F.packet(self.odds_world(live, F.odds(), name="both"))
        self.assertEqual(both["markets"]["moneyline"]["options"][0]["best"]["price"], -170)
        for marker in ("27501", "15003", "19997", "11117", "ESPN Bet", "Live Odds"):
            self.assertNotIn(marker, json.dumps(both))

    def test_a_close_price_is_never_read(self):
        row = F.odds(a_ml_close=-90901, b_ml_close=70707, over_close=-80808, under_close=60606,
                     rounds_total_close=1.5)
        blob = json.dumps(F.packet(self.odds_world(row)))
        for marker in ("90901", "70707", "80808", "60606"):
            self.assertNotIn(marker, blob)

    def test_the_two_blocks_that_are_not_as_of_date_are_kept_only_when_fetched_before_the_start(self):
        """The overall record and the UFC.com career figures include every fight up to their
        fetch. Fetched before the bout they cannot hold its result; fetched at or after the
        start they could, and they are left out with the reason."""
        p = self.packet()
        self.assertIn("career_a", p["sections"])
        self.assertEqual(p["sections"]["career_a"]["values"]["overall_record"]["wins"], 12)
        leaky = build_store(self.root / "leaky", odds=[F.odds()])
        fighters = [dict(f, fetched_utc="2026-10-10T23:30:00Z") for f in leaky.fighters]
        leaky.upsert("fighters", fighters)
        profile = dict(leaky.ufccom_profiles[0], fetched_utc="2026-10-11T00:30:00Z")
        leaky.upsert("ufccom_profiles", [profile])
        q = F.packet(leaky, built_at="2026-10-11T01:00:00Z")
        self.assertNotIn("career_a", q["sections"])
        self.assertNotIn("career_b", q["sections"])
        items = {m["item"] for m in q["missing"]}
        self.assertIn("fighter_a.overall_record", items)
        self.assertIn("fighter_a.ufccom_career", items)
        self.assertNotIn("9.99", json.dumps(q))            # the UFC.com figures never entered

    def test_changing_the_not_as_of_blocks_changes_nothing_else(self):
        before = self.packet()
        profile = dict(self.store.ufccom_profiles[0], sig_strikes_landed_per_min=1.11)
        self.store.upsert("ufccom_profiles", [profile])
        after = self.packet()
        for key in ("fighter_a", "fighter_b", "matchup"):
            self.assertEqual(after["sections"][key], before["sections"][key])
        self.assertEqual(after["markets"], before["markets"])


class TheHoles(World):
    def test_no_odds_row_means_no_markets_and_a_reason(self):
        p = F.packet(self.odds_world())
        self.assertEqual((p["markets"], p["slots"]), ({}, []))
        self.assertIn({"item": "odds", "kind": "absent", "reason": "no odds row for this bout in the store"},
                      p["missing"])

    def test_missing_is_sorted_and_has_no_duplicates(self):
        missing = self.packet()["missing"]
        keys = [(m["item"], m["kind"], m["reason"]) for m in missing]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set().union(*[set(m) for m in missing]), {"item", "kind", "reason"})

    def test_a_fighter_with_no_name_is_labelled_not_invented(self):
        self.store.write("fighters", [])
        p = self.packet()
        self.assertEqual((p["bout"]["fighter_a"]["name"], p["bout"]["fighter_a"]["name_known"]),
                         ("Fighter A", False))
        self.assertEqual(p["markets"]["moneyline"]["options"][0]["selection"], "Fighter A")
        items = {m["item"] for m in p["missing"]}
        self.assertTrue({"fighter_a.name", "fighter_b.name"} <= items)
        self.assertNotIn(F.A, json.dumps(p))

    def test_a_fighter_with_no_fights_in_the_store_says_so(self):
        fighters = self.store.fighters + [dict(self.store.fighters[0], fighter_id="106", name="Fay Fresh",
                                               first_name="Fay", last_name="Fresh", aliases=["fay fresh"])]
        self.store.upsert("fighters", fighters)
        base_bout = dict(self.store.bout_by_id()["9102"])
        self.store.upsert("bouts", [dict(base_bout, bout_id="9103", fighter_a_id="105", fighter_b_id="106")])
        self.store.upsert("odds", [F.odds(bout_id="9103")])
        p = F.packet(self.store, bout_id="9103")
        self.assertIn({"item": "fighter_b", "kind": "absent",
                       "reason": "no UFC fights in the data store before this bout"}, p["missing"])
        self.assertEqual(p["sections"]["fighter_b"]["values"]["record"]["fights"], 0)

    def test_a_thin_sample_is_called_thin(self):
        self.store.upsert("fighters", self.store.fighters + [
            dict(self.store.fighters[0], fighter_id="107", name="Gus Green", first_name="Gus",
                 last_name="Green", aliases=["gus green"])])
        base_bout = dict(self.store.bout_by_id()["9102"])
        self.store.upsert("bouts", [
            dict(base_bout, bout_id="9104", fighter_a_id="107", fighter_b_id="105"),
            dict(COMPLETED_ROW, bout_id="9900", date_utc="2026-02-01T22:00Z", fighter_a_id="107",
                 fighter_b_id="103", winner_id="107", event_id="7900")])
        self.store.upsert("odds", [F.odds(bout_id="9104")])
        p = F.packet(self.store, bout_id="9104")
        thin = [m for m in p["missing"] if m["item"] == "fighter_a" and m["kind"] == "thin"]
        self.assertEqual(len(thin), 1)
        self.assertIn("only 1 UFC fight(s)", thin[0]["reason"])

    def test_a_stale_price_is_flagged_on_every_slot(self):
        p = self.packet(built_at="2026-10-10T20:00:00Z")           # 270 minutes after the quote
        stale = {m["item"] for m in p["missing"] if m["kind"] == "stale"}
        self.assertEqual(stale, set(SLOTS))
        self.assertIn("270 minutes old", next(m["reason"] for m in p["missing"] if m["kind"] == "stale"))
        self.assertEqual([m for m in self.packet()["missing"] if m["kind"] == "stale"], [])

    def test_a_bout_with_no_start_is_built_but_says_it_cannot_be_published(self):
        bout = dict(self.store.bout_by_id()[F.BOUT], date_utc=None)
        self.store.upsert("bouts", [bout])
        p = self.packet()
        self.assertIsNone(p["bout"]["start_utc"])
        self.assertIn("bout.start", {m["item"] for m in p["missing"]})

    def test_the_limits_say_what_is_not_analyzed_and_where_the_counts_come_from(self):
        text = " ".join(self.packet()["limits"])
        self.assertIn("Round betting", text)
        self.assertIn("data store (it begins 2025-01-18)", text)
        self.assertIn("short-notice replacements", text)
        self.assertIn("A UFC round is 5 minutes", text)


COMPLETED_ROW = {
    "bout_id": "9900", "event_id": "7900", "date_utc": "2026-02-01T22:00Z", "match_number": 1,
    "card_segment": "main", "card_segment_raw": "main", "weight_class": "Welterweight",
    "scheduled_rounds": 3, "description": "3 Rnd", "status": "final", "fighter_a_id": "107",
    "fighter_b_id": "103", "winner_id": "107", "result_method": "DEC_UNANIMOUS",
    "result_method_raw": "dec", "result_detail": None, "result_target": None, "end_round": 3,
    "end_time_s": 300.0, "fight_time_s": 900.0, "status_url": SOURCE, "source_url": SOURCE,
    "fetched_utc": FETCHED,
}


class TheSectionsAreTheSheet(World):
    def test_the_fighters_are_measured_as_of_the_bouts_start(self):
        p = self.packet()
        self.assertEqual(p["sections"]["fighter_a"]["as_of"], F.START_ISO)
        self.assertEqual(p["sections"]["matchup"]["as_of"], F.START_ISO)
        self.assertEqual(p["sections"]["fighter_a"]["values"]["record"]["fights"], 5)

    def test_a_figure_carries_its_own_sample(self):
        fig = self.packet()["sections"]["fighter_a"]["values"]["figures"]["control_time_share"]
        self.assertEqual(set(fig) - {"num", "den"}, {"value", "fights", "minutes"})
        self.assertEqual((fig["value"], fig["fights"]), (0.2, 3))      # the 9003 row has no control time

    def test_a_figure_that_cannot_be_computed_says_why(self):
        figs = self.packet()["sections"]["fighter_b"]["values"]["figures"]
        self.assertIsNone(figs["sig_strike_share_distance"]["value"])
        self.assertIn("position-by-target", figs["sig_strike_share_distance"]["reason"])

    def test_the_matchup_holds_the_differences_so_nobody_has_to_subtract(self):
        diffs = self.packet()["sections"]["matchup"]["values"]["differentials"]
        d = diffs["sig_strikes_landed_per_min"]
        self.assertEqual(set(d), {"a", "b", "diff", "thin_sample"})
        self.assertEqual(d["diff"], round(d["a"] - d["b"], 4))
        self.assertNotIn("thin_sample", diffs["ufc_fights"])

    def test_styles_shared_opponents_meetings_physical_and_layoff_are_there(self):
        values = self.packet()["sections"]["matchup"]["values"]
        self.assertEqual(set(values), {"differentials", "styles", "shared_opponents", "previous_meetings",
                                       "physical", "layoff"})
        self.assertEqual(set(values["styles"]["a"]), {"applies", "does_not_apply", "not_assessed"})
        self.assertEqual(values["previous_meetings"][0]["date_utc"], "2026-03-14T22:00Z")
        self.assertEqual(values["previous_meetings"][0]["winner_name"], F.B)
        self.assertEqual(values["physical"]["stance_matchup"], "Orthodox vs Southpaw")
        self.assertGreater(values["layoff"]["a_days"], 0)
        self.assertGreater(values["shared_opponents"]["count"], 0)
        for item in values["shared_opponents"]["items"]:
            self.assertTrue(item["opponent_name"])

    def test_last_three_are_newest_first_and_carry_no_identifier(self):
        last = self.packet()["sections"]["fighter_a"]["values"]["last_three"]
        self.assertEqual([x["date_utc"] for x in last],
                         ["2026-06-13T22:00Z", "2026-03-14T22:00Z", "2025-09-20T22:00Z"])
        self.assertEqual(set(last[0]), {"date_utc", "opponent_name", "result", "method", "detail", "round",
                                        "time_s", "weight_class"})


if __name__ == "__main__":
    unittest.main()
