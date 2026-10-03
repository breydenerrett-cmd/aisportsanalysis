"""source.py: the one module that reads the stores, tested on temp files.

Every store path is injected, so nothing here reads data/processed/ and no
test passes or fails by machine.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analyst import source
from tests import analyst_fixtures as F

GAME = {"game_pk": 849835, "away_team": "NYY", "home_team": "TB"}
OTHER = {"game_pk": 2, "away_team": "BOS", "home_team": "NYM"}
COMMENCE = "2026-10-03T22:31:00Z"


def with_event(rows, event_id="e1", away="New York Yankees", home="Tampa Bay Rays", **extra):
    out = []
    for r in rows:
        r = dict(r, event_id=event_id, commence_time=COMMENCE, away_team=away, home_team=home)
        r.update(extra)
        out.append(r)
    return out


def write(path, rows):
    Path(path).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class PriceRows(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        multibook = with_event(F.multibook_rows())
        multibook += with_event(F.multibook_rows(), event_id="e2", away="Boston Red Sox",
                                home="New York Mets")
        write(self.dir / "mb.jsonl", multibook)
        write(self.dir / "deriv.jsonl", with_event(F.team_total_rows(), away_team="x", home_team="y")
              + with_event(F.team_total_rows(), event_id="eX"))
        write(self.dir / "batter.jsonl", with_event(F.batter_prop_rows()))
        write(self.dir / "pitcher.jsonl", with_event(F.pitcher_prop_rows()))

    def rows(self, games):
        return source.price_rows(
            F.DATE, games, multibook_path=self.dir / "mb.jsonl", derivative_path=self.dir / "deriv.jsonl",
            batter_path=self.dir / "batter.jsonl", pitcher_path=self.dir / "pitcher.jsonl")

    def test_a_game_gets_its_own_rows_by_event_id_from_every_store(self):
        got = self.rows([GAME, OTHER])[849835]
        self.assertEqual(got["event_id"], "e1")
        self.assertEqual(got["team_names"], {"away": "New York Yankees", "home": "Tampa Bay Rays"})
        self.assertEqual(len(got["multibook"]), len(F.multibook_rows()))
        self.assertTrue(all(r["event_id"] == "e1" for r in got["multibook"]))
        self.assertEqual(len(got["team_totals"]), len(F.team_total_rows()))
        self.assertEqual(len(got["batter_props"]), len(F.batter_prop_rows()))
        self.assertEqual(len(got["pitcher_props"]), len(F.pitcher_prop_rows()))

    def test_another_games_rows_do_not_leak_in(self):
        got = self.rows([GAME, OTHER])
        self.assertEqual({r["event_id"] for r in got[2]["multibook"]}, {"e2"})
        self.assertEqual(got[2]["batter_props"], [])
        self.assertEqual(got[2]["team_totals"], [])

    def test_a_game_with_no_multibook_rows_has_no_event_and_no_props(self):
        got = self.rows([{"game_pk": 3, "away_team": "SEA", "home_team": "HOU"}])[3]
        self.assertIsNone(got["event_id"])
        self.assertEqual((got["multibook"], got["batter_props"], got["team_totals"]), ([], [], []))

    def test_both_halves_of_a_doubleheader_are_left_unpriced(self):
        second = dict(GAME, game_pk=849836)
        got = self.rows([GAME, second])
        for pk in (849835, 849836):
            self.assertEqual(got[pk]["multibook"], [])
            self.assertIsNone(got[pk]["event_id"])

    def test_a_row_for_the_wrong_market_in_the_derivative_store_is_ignored(self):
        write(self.dir / "deriv.jsonl", with_event([{"market": "alternate_totals", "book": "dk",
                                                     "line": "3.5", "price": -110}]))
        self.assertEqual(self.rows([GAME])[849835]["team_totals"], [])

    def test_a_missing_store_is_an_empty_one(self):
        got = source.price_rows(F.DATE, [GAME], multibook_path=self.dir / "mb.jsonl",
                                derivative_path=self.dir / "nope.jsonl",
                                batter_path=self.dir / "nope2.jsonl", pitcher_path=self.dir / "nope3.jsonl")
        self.assertEqual(got[849835]["batter_props"], [])
        self.assertTrue(got[849835]["multibook"])

    def test_the_rows_build_the_same_packet_as_the_fixture_rows(self):
        from src.analyst import packet as P
        got = self.rows([GAME])[849835]
        packet = P.build_packet(F.payload(), built_at=F.BUILT_AT, multibook_rows=got["multibook"],
                                team_total_rows=got["team_totals"], batter_prop_rows=got["batter_props"],
                                pitcher_prop_rows=got["pitcher_props"], prop_board=F.prop_board(),
                                team_names=got["team_names"], cfg=F.CFG,
                                section_as_of={"teams": "2026-10-02", "starters": "2026-10-02"})
        self.assertEqual(P.packet_hash(packet), P.packet_hash(F.build()))


class StatsThroughAndBoards(unittest.TestCase):
    def test_stats_through_is_the_newest_result_strictly_before_the_date(self):
        store = {"1": {"date": "2026-10-01"}, "2": {"date": "2026-10-02"}, "3": {"date": "2026-10-03"},
                 "4": {"date": None}}
        self.assertEqual(source.stats_through("2026-10-03", store), "2026-10-02")
        self.assertIsNone(source.stats_through("2026-09-01", {"1": {"date": "2026-10-01"}}))

    def test_a_board_failure_is_an_empty_board_not_an_error(self):
        from src.report import props as props_mod
        with mock.patch.object(props_mod, "board_for_date", side_effect=RuntimeError("no box")):
            self.assertEqual(source.prop_board_for(F.DATE, {1: [{"x": 1}]}), {1: []})
        self.assertEqual(source.prop_board_for(F.DATE, {1: []}), {1: []})

    def test_the_boards_contracts_and_long_shots_are_both_kept(self):
        from src.report import props as props_mod
        board = {"contracts": [{"player": "a"}], "long_shots": [{"player": "b"}]}
        with mock.patch.object(props_mod, "board_for_date", return_value=board) as m:
            out = source.prop_board_for(F.DATE, {1: [{"x": 1}]})
        self.assertEqual([c["player"] for c in out[1]], ["a", "b"])
        self.assertEqual(m.call_args.kwargs["prop_rows"], [{"x": 1}])


if __name__ == "__main__":
    unittest.main()
