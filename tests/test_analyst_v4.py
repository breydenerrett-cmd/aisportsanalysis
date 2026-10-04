"""Prompt v4 and the three defects found in the first published MLB brief (2026-10-04), offline.

1. Customer text said "the packet". Rule 14a asks the model not to, and the checker strikes the word
   in every field a reader sees, so a slip is a struck call, not a published one.
2. A lineup absent for ONE club left no entry in `missing` (only both-absent had one). Each absent
   side now has its own entry, and starters, bullpen and matchup depth are held to the same standard.
3. "4 prop contracts were priced; 0 are analyzed (the rest are left out by the per-game cap)" blamed
   the cap when the cause was one-book prices. The reason now says what actually stopped each prop.

Every packet here is built from the shared synthetic game in `tests/analyst_fixtures.py`: nothing reads
the repo's data or a network.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path

from src.analyst import analyst as A
from src.analyst import critic as C
from src.analyst import ledger, pilot
from src.analyst import packet as packet_mod
from src.analyst import situation_prompt
from src.analyst import ufc_analyst as U
from tests import analyst_fixtures as F
from tests import ufc_analyst_fixtures as UF
from tests.test_analyst_pilot import Env

V3_PROMPT_SHA256 = "a9b1ebe59219e59bb93e0f2e86d7cbba7f0dcbd24eee988812e77187dddb7577"
V3_PROMPT_HASH = "8c667bbbcceb40d1a332fbf9308a97428d422e11cb0f6066de73b58694ee2c34"
V4_PROMPT_SHA256 = "98dc8f5e9021c74ac3631072988d04bbcd6070bf5a1a7927bd8adfe4cd240a35"
V4_PROMPT_HASH = "4c5a4b7d0aa3b15096bbcc89e7029995b54068bac1d37d07fb31dcb97626aecd"
UFC_PROMPT_HASH = "0c924190a80f5c579941ce46d8fee834056b9ec82b7ba207e51ca923c3d28c4a"

RULE_14A = next(l for l in A.SYSTEM_PROMPT.split("\n") if l.startswith("14a."))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reasons_for(packet: dict, item: str) -> list:
    return [m["reason"] for m in packet["missing"] if m["item"] == item]


def items(packet: dict) -> set:
    return {(m["item"], m["kind"]) for m in packet["missing"]}


# ---------------------------------------------------------------------------
# 1. the prompt
# ---------------------------------------------------------------------------

class ThePromptIsVersionFour(unittest.TestCase):
    def test_it_is_v4_and_the_rule_says_what_to_say_instead(self):
        self.assertEqual(A.PROMPT_VERSION, "analyst_prompt_v4")
        self.assertEqual(A.SITUATION_PROMPT_VERSION, "analyst_prompt_v4_situation")
        self.assertIn('call the data "the data" or "what we have", never "the packet"', RULE_14A)
        for field in ("the summary", "reason's claim", "the case against", "what_would_change_it"):
            self.assertIn(field, RULE_14A)
        self.assertIn(RULE_14A, A.SYSTEM_PROMPT)
        self.assertIn(RULE_14A, A.SITUATION_SYSTEM_PROMPT)

    def test_every_other_rule_is_byte_for_byte_v3(self):
        """Take rule 14a out and the text is exactly the v3 prompt that two rows were published under."""
        without = "\n".join(l for l in A.SYSTEM_PROMPT.split("\n") if not l.startswith("14a."))
        self.assertEqual(sha(without), V3_PROMPT_SHA256)

    def test_the_hashes_are_pinned_and_v3_rows_keep_theirs(self):
        self.assertEqual(sha(A.SYSTEM_PROMPT), V4_PROMPT_SHA256)
        self.assertEqual(ledger.prompt_hash(), V4_PROMPT_HASH)
        self.assertNotEqual(V4_PROMPT_HASH, V3_PROMPT_HASH)

    def test_no_rule_number_moved_and_the_situation_section_still_starts_at_17(self):
        rules = [int(n) for n in re.findall(r"^(\d+)\. ", A.SYSTEM_PROMPT, re.M)]
        self.assertEqual(rules, list(range(1, 17)))
        self.assertTrue(situation_prompt.MLB_SITUATION_SECTION.startswith("THE SITUATION\n17. "))

    def test_the_ufc_prompt_and_hash_did_not_move(self):
        self.assertEqual(U.UFC_PROMPT_VERSION, "analyst_ufc_prompt_v1")
        self.assertEqual(U.prompt_hash(), UFC_PROMPT_HASH)
        self.assertNotIn("14a.", U.UFC_SYSTEM_PROMPT)

    def test_the_request_carries_the_v4_prompt(self):
        body = A.build_request(F.build(), F.CFG)
        self.assertEqual(body["system"], A.SYSTEM_PROMPT)
        self.assertIn(RULE_14A, body["system"])


# ---------------------------------------------------------------------------
# 1b. the checker
# ---------------------------------------------------------------------------

def packet_claim(text: str) -> dict:
    return {"claim": text, "evidence": [{"path": "markets.moneyline.lean", "value": "TB"}]}


class TheWordPacketIsStruck(unittest.TestCase):
    def setUp(self):
        self.packet = F.build()

    def good(self) -> dict:
        return F.good_output(self.packet)

    def test_a_clean_answer_is_untouched(self):
        v = C.verify(self.packet, self.good())
        self.assertEqual((v.struck, v.summary_status), ([], "ok"))

    def test_the_word_is_rejected_in_the_helper_only_when_asked(self):
        self.assertEqual(C.banned_words("The packet gives nothing beyond the price."), [])
        self.assertEqual(C.banned_words("The packet gives nothing beyond the price.", internal=True),
                         ["packet"])
        self.assertEqual(C.banned_words("Both packets agree.", internal=True), ["packet"])
        self.assertEqual(C.banned_words("A stray Packet.", internal=True), ["packet"])
        self.assertEqual(C.banned_words("The data gives nothing beyond the price.", internal=True), [])

    def test_a_reason_claim_that_says_packet_strikes_the_call(self):
        out = self.good()
        out["calls"][1]["reasons"][0]["claim"] = "The packet gives nothing beyond the price."
        v = C.verify(self.packet, out)
        self.assertEqual([s["slot_id"] for s in v.struck], ["run_line"])
        self.assertIn("reasons[0] uses the banned word 'packet'", v.struck[0]["problems"])
        self.assertEqual(v.calls[1]["verdict"], "PASS")
        self.assertEqual(v.calls[1]["verification"]["problems"], [])
        self.assertNotIn("packet", str(v.calls[1]).lower().replace("packet_", ""))

    def test_a_case_against_that_says_packet_strikes_the_take(self):
        out = self.good()
        out["calls"][0]["case_against"]["claim"] = (
            "The packet does not say whether the roof is open, and the books favour the home side.")
        v = C.verify(self.packet, out)
        self.assertEqual([s["slot_id"] for s in v.struck], ["moneyline"])
        self.assertIn("case_against uses the banned word 'packet'", v.struck[0]["problems"])
        self.assertEqual(v.calls[0]["verdict"], "PASS")

    def test_what_would_change_it_that_says_packet_strikes_the_call(self):
        out = self.good()
        out["calls"][2]["what_would_change_it"] = "Anything the packet does not hold yet."
        v = C.verify(self.packet, out)
        self.assertEqual([s["slot_id"] for s in v.struck], ["total"])
        self.assertIn("what_would_change_it uses the banned word 'packet'", v.struck[0]["problems"])

    def test_a_summary_that_says_packet_is_withheld_and_the_calls_still_publish(self):
        out = self.good()
        out["summary"] += " Nothing else in the packet moves me."
        v = C.verify(self.packet, out)
        self.assertEqual(v.summary_status, "withheld")
        self.assertIsNone(v.summary)
        self.assertIn("the summary uses the banned word 'packet'", v.summary_problems)
        self.assertEqual(v.struck, [])

    def test_an_evidence_path_is_not_prose(self):
        out = self.good()
        out["calls"][0]["reasons"][0]["evidence"][0]["path"] = "packet.markets.moneyline.options[1].best.price"
        v = C.verify(self.packet, out)
        problems = " ".join(v.struck[0]["problems"])
        self.assertIn("paths start at the packet's own top-level key", problems)
        self.assertNotIn("banned word", problems)

    def test_the_ufc_analyst_is_not_held_to_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkt = UF.packet(UF.make_store(Path(tmp)))
        out = UF.good_output(pkt)
        out["calls"][0]["reasons"][0]["claim"] = "The packet has the numbers."
        out["summary"] += " Nothing else in the packet moves me."
        v = U.verify(pkt, out)
        text = " ".join(" ".join(s["problems"]) for s in v.struck) + " ".join(v.summary_problems)
        self.assertNotIn("banned word 'packet'", text)

    def test_the_pilot_check_reports_the_strike(self):
        out = self.good()
        out["summary"] += " Nothing else in the packet moves me."
        out["calls"][1]["reasons"][0]["claim"] = "The packet gives nothing beyond the price."
        report = pilot.evaluate(self.packet, out)
        self.assertEqual(report.summary_status, "withheld")
        struck = [c for c in report.calls if not c.kept]
        self.assertEqual([c.slot_id for c in struck], ["run_line"])
        lines = []
        pilot.print_report(report, lines.append)
        self.assertIn("the banned word 'packet'", "\n".join(lines))


class ThePilotWorksWithV4(Env):
    def test_prepare_check_and_publish_carry_v4(self):
        self.assertEqual(self.prepare(), 0, self.text)
        meta = pilot.load_prepared(str(self.folder)).meta
        self.assertEqual((meta["prompt_version"], meta["prompt_hash"]),
                         ("analyst_prompt_v4", V4_PROMPT_HASH))
        request = (self.folder / "request.json").read_text(encoding="utf-8")
        self.assertIn("14a. Everything a reader sees", request)
        self.out.clear()
        self.assertEqual(pilot.check(str(self.folder), self.good_response(), out=self.out.append), 0)
        self.assertRegex(self.text, r"totals: \d+ calls, \d+ kept, 0 struck")
        self.assertEqual(self.publish(), 0, self.text)
        row = self.store_rows()[0]
        self.assertEqual((row["prompt_version"], row["prompt_hash"]),
                         ("analyst_prompt_v4", V4_PROMPT_HASH))

    def test_a_folder_prepared_under_v3_cannot_be_published_under_v4(self):
        """The two briefs published today were prepared under v3. A new brief is prepared afresh:
        a folder whose recorded prompt is not the current one is refused, so a response written for the
        old request can never be frozen as an answer to the new one."""
        self.assertEqual(self.prepare(), 0, self.text)
        meta_path = self.folder / "prepare.json"
        meta = pilot._read_json(meta_path, "prepare.json")
        meta.update(prompt_version="analyst_prompt_v3", prompt_hash=V3_PROMPT_HASH)
        pilot._write_json(meta_path, meta)
        self.assertEqual(self.publish(), 2)
        self.assertIn("has changed since this game was prepared", self.text)


# ---------------------------------------------------------------------------
# 2. one-sided gaps in `missing`
# ---------------------------------------------------------------------------

def batters(n: int) -> list:
    return [{"order": i + 1, "name": f"Player {i}", "position": "DH", "person_id": 1000 + i}
            for i in range(n)]


def lineup(side_batters: list) -> dict:
    return {"batters": side_batters, "handedness": {"L": 4, "R": 5}, "platoon_advantage": 0.5,
            "faces_starter_throwing": "R", "vs_pitch": {}}


def with_lineups(away: list, home: list):
    def edit(advanced):
        advanced["sections"]["lineups"] = {"away": lineup(away), "home": lineup(home)}
        advanced["gaps"].pop("lineups", None)
    return edit


class OneSidedLineups(unittest.TestCase):
    def test_an_absent_road_lineup_is_listed_by_itself(self):
        p = F.build(edit=with_lineups([], batters(9)))
        self.assertEqual(p["sections"]["lineups"]["values"]["away"]["batters"], [])
        self.assertEqual(len(p["sections"]["lineups"]["values"]["home"]["batters"]), 9)
        self.assertIn(("lineups.away", "absent"), items(p))
        self.assertNotIn(("lineups.home", "absent"), items(p))
        self.assertNotIn(("lineups", "absent"), items(p))
        self.assertEqual(reasons_for(p, "lineups.away"),
                         ["the away lineup is not posted yet, or was not fetched"])

    def test_an_absent_home_lineup_is_listed_by_itself(self):
        p = F.build(edit=with_lineups(batters(9), []))
        self.assertIn(("lineups.home", "absent"), items(p))
        self.assertNotIn(("lineups.away", "absent"), items(p))

    def test_a_side_missing_from_the_section_altogether_counts_as_absent(self):
        def edit(advanced):
            advanced["sections"]["lineups"] = {"home": lineup(batters(9))}
            advanced["gaps"].pop("lineups", None)
        p = F.build(edit=edit)
        self.assertIn(("lineups.away", "absent"), items(p))

    def test_both_posted_lists_nothing(self):
        p = F.build(edit=with_lineups(batters(9), batters(9)))
        self.assertFalse([m for m in p["missing"] if m["item"].startswith("lineups")])

    def test_both_absent_in_a_present_section_lists_both_sides(self):
        p = F.build(edit=with_lineups([], []))
        self.assertTrue({("lineups.away", "absent"), ("lineups.home", "absent")} <= items(p))

    def test_both_absent_the_usual_way_still_says_lineup_not_posted_yet(self):
        p = F.build()
        self.assertEqual(reasons_for(p, "lineups"), ["lineup not posted yet, or not fetched"])
        self.assertFalse([m for m in p["missing"] if m["item"] in ("lineups.away", "lineups.home")])


class OneSidedStarters(unittest.TestCase):
    def starters(self, **flags):
        def edit(advanced):
            advanced["sections"]["starters"].update(flags)
        return F.build(edit=edit)

    def test_one_unknown_starter_is_listed_by_itself(self):
        p = self.starters(away_sp_known=False)
        self.assertIn(("starters.away", "absent"), items(p))
        self.assertNotIn(("starters.home", "absent"), items(p))
        self.assertEqual(reasons_for(p, "starters.away"),
                         ["the away probable starter has no stored pitching log"])

    def test_one_thin_starter_is_listed_by_itself(self):
        p = self.starters(home_sp_thin=True)
        self.assertIn(("starters.home", "thin"), items(p))
        self.assertNotIn(("starters.away", "thin"), items(p))

    def test_a_starter_flag_that_is_absent_altogether_is_not_silent(self):
        def edit(advanced):
            del advanced["sections"]["starters"]["home_sp_known"]
        p = F.build(edit=edit)
        self.assertIn(("starters.home", "absent"), items(p))


def pen(*teams) -> dict:
    return {t: {"team": t, "relievers": r, "reliever_count": len(r)} for t, r in teams}


ARM = [{"name": "Reliever One", "innings": 1.0}]


def with_bullpen(values: dict):
    def edit(advanced):
        advanced["sections"]["bullpen"] = values
    return edit


class OneSidedBullpen(unittest.TestCase):
    def test_a_club_left_out_of_the_section_is_listed_by_itself(self):
        # briefing.py drops a club with no bullpen data from the section instead of showing it empty
        p = F.build(edit=with_bullpen(pen(("TB", ARM))))
        self.assertIn(("bullpen.away", "absent"), items(p))
        self.assertNotIn(("bullpen.home", "absent"), items(p))
        self.assertNotIn(("bullpen", "absent"), items(p))
        self.assertEqual(reasons_for(p, "bullpen.away"),
                         ["no reliever appearances recorded for the away club in the window"])

    def test_a_club_with_an_empty_list_is_listed_by_itself(self):
        p = F.build(edit=with_bullpen(pen(("NYY", ARM), ("TB", []))))
        self.assertIn(("bullpen.home", "absent"), items(p))
        self.assertNotIn(("bullpen.away", "absent"), items(p))

    def test_both_empty_keeps_the_either_club_line_and_adds_no_per_side_entry(self):
        p = F.build(edit=with_bullpen(pen(("NYY", []), ("TB", []))))
        self.assertEqual(reasons_for(p, "bullpen"),
                         ["no reliever appearances recorded for either club in the window"])
        self.assertFalse([m for m in p["missing"] if m["item"] in ("bullpen.away", "bullpen.home")])

    def test_only_one_club_present_and_empty_says_either_club(self):
        p = F.build(edit=with_bullpen(pen(("TB", []))))
        self.assertEqual(len(reasons_for(p, "bullpen")), 1)

    def test_both_present_lists_nothing(self):
        p = F.build(edit=with_bullpen(pen(("NYY", ARM), ("TB", ARM))))
        self.assertFalse([m for m in p["missing"] if m["item"].startswith("bullpen")])

    def test_keys_that_are_neither_club_fall_back_to_the_older_rule(self):
        p = F.build(edit=with_bullpen(pen(("XXX", ARM))))
        self.assertFalse([m for m in p["missing"] if m["item"].startswith("bullpen")])


def depth_side(team: str, reason: str = None) -> dict:
    if reason:
        return {"team": team, "reason": reason}
    return {"team": team, "opposing_starter_throws": "R", "concentration": {"top": 0.5, "bottom": 0.5}}


def with_depth(away: dict, home: dict):
    def edit(advanced):
        advanced["sections"]["matchup_depth"] = {"cutoff": "2026-10-02", "away": away, "home": home}
    return edit


class OneSidedMatchupDepth(unittest.TestCase):
    NO_LINEUP = "no posted away lineup stored, so there is no unit to decompose"

    def test_one_side_without_depth_is_listed_by_itself_with_its_own_reason(self):
        p = F.build(edit=with_depth(depth_side("NYY", self.NO_LINEUP), depth_side("TB")))
        self.assertIn(("matchup_depth.away", "absent"), items(p))
        self.assertNotIn(("matchup_depth.home", "absent"), items(p))
        self.assertEqual(reasons_for(p, "matchup_depth.away"), [self.NO_LINEUP])

    def test_a_side_that_is_not_an_object_is_not_silent(self):
        def edit(advanced):
            advanced["sections"]["matchup_depth"] = {"cutoff": "2026-10-02", "home": depth_side("TB")}
        p = F.build(edit=edit)
        self.assertEqual(reasons_for(p, "matchup_depth.away"),
                         ["no matchup depth was built for the away lineup"])

    def test_both_built_lists_nothing(self):
        p = F.build(edit=with_depth(depth_side("NYY"), depth_side("TB")))
        self.assertFalse([m for m in p["missing"] if m["item"].startswith("matchup_depth")])

    def test_a_whole_section_gap_still_comes_from_the_payloads_gap(self):
        def edit(advanced):
            advanced["gaps"]["matchup_depth"] = "no posted lineup for this game, so there is no unit to decompose"
        p = F.build(edit=edit)
        self.assertEqual(reasons_for(p, "matchup_depth"),
                         ["no posted lineup for this game, so there is no unit to decompose"])


class ANewPacketHashesDifferentlyOnlyWhereTheHoleIs(unittest.TestCase):
    def test_the_fixture_packet_without_a_one_sided_hole_hashes_as_it_did(self):
        # pinned in tests/test_situation_analyst.py (MLB_PACKET_SHA256) as well
        self.assertEqual(packet_mod.packet_hash(F.build()),
                         "d5f4be75e1dbcfdc486b0128109b2fbe18742debcaeb68c39924fc5ff8206110")

    def test_a_one_sided_hole_changes_the_hash_of_that_packet_only(self):
        a = F.build(edit=with_lineups(batters(9), batters(9)))
        b = F.build(edit=with_lineups([], batters(9)))
        self.assertNotEqual(packet_mod.packet_hash(a), packet_mod.packet_hash(b))


# ---------------------------------------------------------------------------
# 3. the prop line
# ---------------------------------------------------------------------------

def one_book(rows: list, book: str = "draftkings") -> list:
    return [r for r in rows if r.get("book") == book]


def hits_rows(players: list) -> list:
    rows = []
    for name in players:
        for side, prices in (("Over", (-120, -125)), ("Under", (100, 105))):
            for book, price in zip(("draftkings", "fanduel"), prices):
                rows.append({"observed_utc": F.CAPTURED, "book": book, "market": "batter_hits",
                             "player": name, "line": "0.5", "side": side, "price": price})
    return rows


def prop_line(packet: dict) -> str:
    (reason,) = reasons_for(packet, "props")
    return reason


class ThePropLineSaysWhatActuallyHappened(unittest.TestCase):
    def test_the_same_four_props_each_from_one_book_are_not_blamed_on_the_cap(self):
        """The SD-at-MIL case: four props priced, none analyzed, a cap of 16."""
        p = F.build(batter_prop_rows=one_book(F.batter_prop_rows()),
                    pitcher_prop_rows=one_book(F.pitcher_prop_rows()))
        self.assertEqual([m for m in p["markets"].values() if m["market"] == "prop"], [])
        self.assertEqual(prop_line(p), "4 player props were priced, each by fewer than 2 books, "
                                       "so none is analyzed")
        self.assertNotIn("cap", prop_line(p))
        self.assertEqual(F.CFG["max_props_per_game"], 16)

    def test_one_prop_from_one_book_is_said_in_the_singular(self):
        p = F.build(batter_prop_rows=one_book(F.batter_prop_rows())[:2],
                    pitcher_prop_rows=[], prop_board=[])
        self.assertEqual(prop_line(p), "1 player prop was priced, by fewer than 2 books, "
                                       "so it is not analyzed")

    def test_the_book_minimum_in_the_line_is_the_configured_one(self):
        cfg = dict(F.CFG, min_books_for_prop=3)
        p = F.build(cfg=cfg)
        self.assertEqual(prop_line(p), "4 player props were priced, each by fewer than 3 books, "
                                       "so none is analyzed")

    def test_the_cap_is_named_when_the_cap_is_what_stopped_them(self):
        p = F.build(cfg=dict(F.CFG, max_props_per_game=2))
        self.assertEqual(prop_line(p), "4 player props were priced and 2 analyzed: "
                                       "2 were left out by the limit of 2 props per game")

    def test_one_left_out_by_the_cap_is_said_in_the_singular(self):
        p = F.build(cfg=dict(F.CFG, max_props_per_game=3))
        self.assertEqual(prop_line(p), "4 player props were priced and 3 analyzed: "
                                       "1 was left out by the limit of 3 props per game")

    def test_the_one_market_limit_is_named_when_that_is_what_stopped_them(self):
        p = F.build(batter_prop_rows=hits_rows(["Alpha One", "Beta Two", "Gamma Three"]),
                    pitcher_prop_rows=[], prop_board=[], cfg=dict(F.CFG, max_props_per_game=4))
        self.assertEqual(len([m for m in p["markets"].values() if m["market"] == "prop"]), 2)
        self.assertEqual(prop_line(p), "3 player props were priced and 2 analyzed: "
                                       "1 was left out by the limit of 2 props from one market")

    def test_both_causes_at_once_are_both_named(self):
        rows = hits_rows(["Alpha One", "Beta Two", "Gamma Three"]) + one_book(
            [dict(r, player="Delta Four") for r in hits_rows(["Delta Four"])])
        p = F.build(batter_prop_rows=rows, pitcher_prop_rows=[], prop_board=[],
                    cfg=dict(F.CFG, max_props_per_game=4))
        self.assertEqual(prop_line(p),
                         "4 player props were priced and 2 analyzed: 1 player prop had fewer than 2 books quoting it "
                         "and 1 was left out by the limit of 2 props from one market")

    def test_nothing_priced_still_says_so_and_all_analyzed_says_nothing(self):
        none = F.build(batter_prop_rows=[], pitcher_prop_rows=[], prop_board=[])
        self.assertEqual(prop_line(none), "no player-prop prices were captured for this game")
        self.assertEqual(reasons_for(F.build(), "props"), [])

    def test_the_item_and_kind_are_what_they_were(self):
        p = F.build(cfg=dict(F.CFG, max_props_per_game=2))
        self.assertIn(("props", "thin"), items(p))


# ---------------------------------------------------------------------------
# the reader sees `missing`: none of it may use our word
# ---------------------------------------------------------------------------

class NoReasonInMissingSaysPacket(unittest.TestCase):
    def packets(self):
        yield F.build()
        yield F.build(multibook_rows=[], team_total_rows=[], batter_prop_rows=[],
                      pitcher_prop_rows=[], prop_board=[])
        yield F.build(built_at="2026-10-03T21:00:00Z")
        yield F.build(section_as_of={"teams": "2026-09-23", "starters": "2026-09-20"})
        yield F.build(cfg=dict(F.CFG, max_props_per_game=2))
        yield F.build(batter_prop_rows=one_book(F.batter_prop_rows()),
                      pitcher_prop_rows=one_book(F.pitcher_prop_rows()))
        yield F.build(edit=with_lineups([], batters(9)))
        yield F.build(edit=with_bullpen(pen(("TB", ARM))))
        yield F.build(edit=with_depth(depth_side("NYY", "no posted away lineup stored, so there is no "
                                                        "unit to decompose"), depth_side("TB")))

    def test_every_reason_is_free_of_the_internal_word_and_the_banned_ones(self):
        seen = 0
        for p in self.packets():
            for m in p["missing"]:
                seen += 1
                self.assertEqual(C.banned_words(m["reason"], internal=True), [], m)
        self.assertGreater(seen, 20)

    def test_the_no_prices_lines_say_analysis_not_packet(self):
        p = F.build(multibook_rows=[], team_total_rows=[], batter_prop_rows=[],
                    pitcher_prop_rows=[], prop_board=[])
        self.assertEqual(reasons_for(p, "moneyline"),
                         ["no moneyline prices were captured before this analysis was built"])


if __name__ == "__main__":
    unittest.main()
