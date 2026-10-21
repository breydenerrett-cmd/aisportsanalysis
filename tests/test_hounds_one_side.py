"""One side per game (src/hounds/one_side.py): a hound never holds two positions that can lose together.

THE STORY (2026-10-21): a member's hound took the 76ers moneyline at +140 AND the Knicks -4.5 at even money on
one NBA game. If the Knicks win by 1 to 4, both lose. The v2 engine de-duplicated per bet id (hound, event,
market), so a moneyline rule and a spread rule could each take their own side of the same game.

Every test here failed on the code before the fix (the story is pinned in the commit). No FastAPI, no stored
data: boards are the shared fixtures, and the NBA game is built in memory below.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from collections import Counter
from unittest import mock

from src.hounds import one_side, user_engine, user_spec
from src.hounds.interact import common, fire, manual
from src.ledger.chain import HashChainLedger
from tests import _hounds_rules_fixtures as F
from tests._hounds_user_fixtures import BOOKS, T_LOCK, T_OPEN, board_rows, hound as v1_hound, utc

NOW = F.NOW
KNICKS, SIXERS = "New York Knicks", "Philadelphia 76ers"


def nba_rows() -> list:
    """The member's game: Knicks home, 76ers away. At the lock board the 76ers moneyline averages +140, the
    Knicks -165, and the Knicks -4.5 spread pays even money (+100) with the 76ers +4.5 at -120."""
    out = []
    for t in (T_OPEN, T_LOCK):
        out += board_rows(t, event_id="nba0001", home=KNICKS, away=SIXERS, sport="NBA",
                          moneyline=[(b, -165, 140) for b in BOOKS],
                          spread=(-4.5, [(b, 100, -120) for b in BOOKS]),
                          total=(221.5, [(b, -110, -110) for b in BOOKS]))
    return out


def nba_rule(**over) -> dict:
    return F.rule(sports=["NBA"], **over)


def dog(rules, hid="u-jsmooth", **over) -> dict:
    return F.hound(hid, rules=rules, **{"max_bets_per_day": 5, **over})


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "ledger.jsonl")
        players = F.patch_players()
        players.start()
        self.addCleanup(players.stop)

    def run_day(self, hounds, rows, *, ledger=None, now=NOW):
        return user_engine.run(F.DATE, hounds, rows, ledger=ledger or self.ledger, now=now, mode="live",
                               game_pk_index={}, prop_rows=[], facts=F.facts())

    def bets(self, ledger=None):
        return [r for r in user_engine.read_ledger(ledger or self.ledger) if r.get("kind") == user_engine.KIND_BET]


class TheMembersPair(_Base):
    def test_a_moneyline_rule_and_the_opposite_spread_rule_take_one_bet(self):
        h = dog([nba_rule(markets=["moneyline"], side="away"), nba_rule(markets=["spread"], side="home")])
        report = self.run_day([h], nba_rows())
        placed = self.bets()
        self.assertEqual(len(placed), 1, [(b["market"], b["selection"]) for b in placed])
        self.assertEqual(report["skipped"].get(one_side.CODE_DEAD), 1)

    def test_the_survivor_is_the_one_the_hounds_own_rank_by_puts_first_never_the_better_price_after_the_fact(self):
        rules = [nba_rule(markets=["moneyline"], side="away"), nba_rule(markets=["spread"], side="home")]
        # shortest_price ranks the +100 spread (the Knicks) ahead of the +140 moneyline; longest_price the reverse
        short = self.run_day([dog(rules, rank_by="shortest_price")], nba_rows())
        self.assertEqual([b["market"] for b in self.bets()], ["spread"])
        os.remove(self.ledger)
        self.run_day([dog(rules, rank_by="longest_price")], nba_rows())
        self.assertEqual([b["market"] for b in self.bets()], ["moneyline"])
        self.assertEqual(short["skipped"].get(one_side.CODE_DEAD), 1)

    def test_a_same_team_moneyline_and_spread_are_redundant_so_one_bet(self):
        h = dog([nba_rule(markets=["moneyline"], side="away"), nba_rule(markets=["spread"], side="away")])
        report = self.run_day([h], nba_rows())
        self.assertEqual(len(self.bets()), 1)
        self.assertEqual(report["skipped"].get(one_side.CODE_SAME), 1)

    def test_one_rule_naming_both_markets_with_either_side_still_takes_one_side(self):
        h = dog([nba_rule(markets=["moneyline", "spread"], side="either", price_min=-199, price_max=1000)])
        self.run_day([h], nba_rows())
        sides = {(b["market"], b["side"]) for b in self.bets()}
        self.assertEqual(len({s for _m, s in sides}), 1, sides)
        self.assertEqual(len(self.bets()), 1)

    def test_a_side_and_a_total_are_not_contradictory_so_two_bets_when_both_rules_exist(self):
        h = dog([nba_rule(markets=["moneyline"], side="away"), nba_rule(markets=["total"], side="over")])
        self.run_day([h], nba_rows())
        self.assertEqual(sorted(b["market"] for b in self.bets()), ["moneyline", "total"])

    def test_a_side_without_a_total_rule_never_gets_a_total(self):
        h = dog([nba_rule(markets=["moneyline"], side="away")])
        self.run_day([h], nba_rows())
        self.assertEqual([b["market"] for b in self.bets()], ["moneyline"])

    def test_another_game_is_a_fresh_slate(self):
        rows = nba_rows()
        for t in (T_OPEN, T_LOCK):
            rows += board_rows(t, event_id="nba0002", home="Boston Celtics", away="Miami Heat", sport="NBA",
                               moneyline=[(b, -150, 130) for b in BOOKS],
                               spread=(-3.5, [(b, 100, -120) for b in BOOKS]))
        h = dog([nba_rule(markets=["moneyline"], side="away"), nba_rule(markets=["spread"], side="home")])
        self.run_day([h], rows)
        per_game = Counter(b["event_id"] for b in self.bets())
        self.assertEqual(per_game, {"nba0001": 1, "nba0002": 1})

    def test_the_classic_engine_is_held_to_the_same_rule(self):
        # a classic hound has one side rule across its markets; "market moved toward" can point a moneyline and a
        # spread at different teams on a game whose two boards moved differently
        rows = board_rows(T_OPEN, moneyline=[(b, -125, 105) for b in BOOKS],
                          spread=(-1.5, [(b, 160, -190) for b in BOOKS]))
        rows += board_rows(T_LOCK, moneyline=[(b, -140, 120) for b in BOOKS],      # moved toward home
                           spread=(-1.5, [(b, 130, -150) for b in BOOKS]))         # moved toward away
        h = v1_hound("u-classic", side_rule="market_moved_toward", markets=["moneyline", "spread"],
                     price_min=-199, price_max=1000)
        self.run_day([h], rows, now=utc("2026-10-20T21:30:00Z"))
        self.assertEqual(len(self.bets()), 1)


class TheDeadZone(_Base):
    """76ers ML + Knicks -4.5 can never both win, and a Knicks win by 1 to 4 loses both (owner, 2026-10-21)."""

    PHI_ML = {"market": "moneyline", "side": "away", "line": None}
    NYK_MINUS = {"market": "spread", "side": "home", "line": -4.5}
    NYK_PLUS = {"market": "spread", "side": "home", "line": 4.5}
    PHI_PLUS = {"market": "spread", "side": "away", "line": 4.5}
    NYK_ML = {"market": "moneyline", "side": "home", "line": None}

    def test_dead_zone_is_true_for_the_exact_case(self):
        self.assertTrue(one_side.dead_zone(self.PHI_ML, self.NYK_MINUS))
        self.assertTrue(one_side.dead_zone(self.NYK_MINUS, self.PHI_ML))       # order does not matter

    def test_dead_zone_is_false_when_a_middle_exists(self):
        # 76ers ML + Knicks +4.5: both win when the 76ers win by 1 to 4 (a middle), so a hedge, not a dead zone
        self.assertFalse(one_side.dead_zone(self.PHI_ML, {"market": "spread", "side": "home", "line": 4.5}))

    def test_dead_zone_is_false_for_the_same_teams_moneyline_and_spread(self):
        self.assertFalse(one_side.dead_zone(self.NYK_ML, self.NYK_MINUS))
        self.assertFalse(one_side.dead_zone(self.PHI_ML, {"market": "spread", "side": "away", "line": 4.5}))

    def test_dead_zone_ignores_what_is_not_two_side_bets(self):
        self.assertFalse(one_side.dead_zone(self.PHI_ML, {"market": "total", "side": "over", "line": 221.5}))
        self.assertFalse(one_side.dead_zone(self.PHI_ML, {"market": "spread", "side": "home", "line": None}))

    def test_two_moneylines_on_opposite_teams_are_not_a_dead_zone(self):
        # a tie is a push for both, so nothing loses both; the one-side rule still blocks the pair as "other side"
        self.assertFalse(one_side.dead_zone(self.PHI_ML, self.NYK_ML))

    def test_the_exact_case_places_only_the_higher_ranked_bet(self):
        """PHI ML +140 and NYK -4.5 at +100 on one NBA game."""
        rules = [nba_rule(markets=["moneyline"], side="away"), nba_rule(markets=["spread"], side="home")]
        for rank_by, expected in (("longest_price", "moneyline"), ("shortest_price", "spread")):
            with self.subTest(rank_by=rank_by):
                if os.path.exists(self.ledger):
                    os.remove(self.ledger)
                report = self.run_day([dog(rules, rank_by=rank_by)], nba_rows())
                placed = self.bets()
                self.assertEqual([b["market"] for b in placed], [expected])
                self.assertEqual({b["selection"] for b in placed} & {"Philadelphia 76ers to win",
                                                                     "New York Knicks -4.5"}, {placed[0]["selection"]})
                self.assertEqual(report["skipped"].get(one_side.CODE_DEAD), 1)

    def test_the_append_guard_refuses_the_dead_zone_partner_with_the_plain_reason(self):
        first = dog([nba_rule(markets=["moneyline"], side="away")])
        self.run_day([first], nba_rows())
        self.assertEqual([(b["market"], b["price"]) for b in self.bets()], [("moneyline", 140)])
        second = dog([nba_rule(markets=["spread"], side="home")])
        with self.assertLogs("linehound.hounds.one_side", level="INFO") as logs:
            report = self.run_day([second], nba_rows())
        self.assertEqual(len(self.bets()), 1)
        self.assertEqual(report["skipped"].get(one_side.CODE_DEAD), 1)
        self.assertIn("these two bets could both lose and can never both win", " ".join(logs.output))
        book = one_side.Book.from_rows(self.bets())
        self.assertEqual(book.refusal("u-jsmooth", "nba0001", "spread", "home", None, -4.5), one_side.CODE_DEAD)
        self.assertEqual(one_side.reason_text(one_side.CODE_DEAD),
                         "these two bets could both lose and can never both win")

    def test_a_hedge_with_a_middle_is_still_one_side_but_not_called_a_dead_zone(self):
        # Knicks ML + 76ers +4.5: both win when the Knicks win by 1 to 4. Still two sides, so still refused,
        # with the ordinary words.
        book = one_side.Book.from_rows([{"kind": "hound_user_bet", "hound_id": "h", "event_id": "e",
                                         "market": "moneyline", "side": "home", "line": None}])
        self.assertEqual(book.refusal("h", "e", "spread", "away", None, 4.5), one_side.CODE_OTHER)


class TotalsAreOneToo(_Base):
    def test_a_total_over_already_on_the_ledger_refuses_the_under(self):
        # the over carries an id the under's id does not match (a row written by another path), so only the
        # one-side guard, not the per-bet dedupe, can stop the under
        over = dog([nba_rule(markets=["total"], side="over")], hid="u-tot")
        self.run_day([over], nba_rows(), ledger=self.ledger + ".seed")
        seed = dict(self.bets(self.ledger + ".seed")[0])
        for key in ("prev_hash", "row_hash"):
            seed.pop(key)
        seed["bet_id"] = "legacy-total-over"
        HashChainLedger(self.ledger).append(seed)
        under = dog([nba_rule(markets=["total"], side="under")], hid="u-tot")
        report = self.run_day([under], nba_rows())
        self.assertEqual([b["side"] for b in self.bets()], ["over"])
        self.assertEqual(report["skipped"].get(one_side.CODE_OTHER), 1)

    def test_two_rules_on_the_total_still_make_at_most_one_total(self):
        h = dog([nba_rule(markets=["total"], side="over"), nba_rule(markets=["total"], side="under")])
        self.run_day([h], nba_rows())
        self.assertEqual(len(self.bets()), 1)


class PlayerPropsAreUnaffected(_Base):
    def test_a_prop_and_a_side_and_a_total_can_all_stand_but_never_over_and_under_of_one_stat(self):
        h = F.hound("u-props", max_bets_per_day=5, rules=[
            F.rule(markets=["moneyline"], side="away"), F.rule(markets=["total"], side="over"),
            F.rule(markets=["batter_total_bases"], side="either", price_min=-199, price_max=1000)])
        user_engine.run(F.DATE, [h], F.standard_rows(), ledger=self.ledger, now=NOW, mode="live",
                        game_pk_index=F.PK_INDEX, prop_rows=F.standard_props(), facts=F.facts())
        kinds = Counter(b["market"] for b in self.bets())
        self.assertEqual(kinds["moneyline"], 1)
        self.assertEqual(kinds["total"], 1)
        per_player = Counter((b["market"], b["player"]) for b in self.bets() if b["player"])
        self.assertTrue(all(n == 1 for n in per_player.values()), per_player)
        self.assertGreaterEqual(sum(per_player.values()), 1)

    def test_the_guard_refuses_the_under_of_a_stat_the_hound_already_holds_the_over_of(self):
        book = one_side.Book.from_rows([{"kind": "hound_user_bet", "hound_id": "h", "event_id": "e",
                                         "market": "batter_hits", "side": "over", "player": "Pat Slugger"}])
        self.assertEqual(book.refusal("h", "e", "batter_hits", "under", "pat slugger"), one_side.CODE_OTHER)
        self.assertIsNone(book.refusal("h", "e", "batter_hits", "under", "Sam Contact"))
        self.assertIsNone(book.refusal("h", "e", "batter_total_bases", "under", "Pat Slugger"))
        self.assertIsNone(book.refusal("h", "e", "total", "under"))


class TheAppendGuard(_Base):
    def test_a_second_run_cannot_add_the_opposite_side_when_the_first_is_in_the_ledger(self):
        first = dog([nba_rule(markets=["moneyline"], side="away")])
        self.run_day([first], nba_rows())
        second = dog([nba_rule(markets=["spread"], side="home")])          # same hound id, a later edit
        report = self.run_day([second], nba_rows())
        self.assertEqual([b["market"] for b in self.bets()], ["moneyline"])
        self.assertEqual(report["bets_written"], 0)
        self.assertEqual(report["skipped"].get(one_side.CODE_DEAD), 1)

    def test_a_different_engine_path_is_held_to_it_too(self):
        # the classic engine places the 76ers moneyline; the rule-set engine then tries the Knicks spread
        classic = v1_hound("u-jsmooth", sports=["NBA"], side_rule="underdog", price_min=100, price_max=300)
        self.run_day([classic], nba_rows())
        self.assertEqual([b["market"] for b in self.bets()], ["moneyline"])
        rules = dog([nba_rule(markets=["spread"], side="home")])
        self.run_day([rules], nba_rows())
        self.assertEqual(len(self.bets()), 1)

    def test_a_refusal_is_logged_in_plain_words(self):
        h = dog([nba_rule(markets=["moneyline"], side="away"), nba_rule(markets=["spread"], side="home")])
        with self.assertLogs("linehound.hounds.one_side", level="INFO") as logs:
            self.run_day([h], nba_rows())
        self.assertIn("these two bets could both lose and can never both win", "\n".join(logs.output))

    def test_the_ledger_is_never_edited_and_an_existing_pair_stays(self):
        # a pair written before the rule existed: both rows stay, and the hound adds nothing more on that game
        pair = [{"kind": user_engine.KIND_BET, "hound_id": "u-jsmooth", "event_id": "nba0001",
                 "bet_id": "old-1", "market": "moneyline", "side": "away"},
                {"kind": user_engine.KIND_BET, "hound_id": "u-jsmooth", "event_id": "nba0001",
                 "bet_id": "old-2", "market": "spread", "side": "home"}]
        chain = HashChainLedger(self.ledger)
        for row in pair:
            chain.append(dict(row, slate_date=F.DATE))
        before = open(self.ledger, "rb").read()
        h = dog([nba_rule(markets=["total"], side="over")])
        self.run_day([h], nba_rows())
        after = open(self.ledger, "rb").read()
        self.assertTrue(after.startswith(before))
        self.assertEqual(len(self.bets()), 3)                    # the old pair, plus a total (a different slot)


class LiveManualSend(_Base):
    """The Live "Send a hound" path (manual.record) writes to its own ledger; it must still look at the dog's
    rule ledger too, or one tap adds the other side of a game the engine already took."""

    def setUp(self):
        super().setUp()
        fire.clear_cache()
        self.manual_ledger = os.path.join(self._tmp.name, "hounds_manual_v1.jsonl")
        patch = mock.patch.object(user_engine, "ledger_path", lambda p=None: p or self.ledger)
        patch.start()
        self.addCleanup(patch.stop)

    def _dog(self, **over):
        h = v1_hound("u-manual", **over)
        h.update({"owner_user_id": 7, "status": "running", "name": "Dog Days", "tagline": "", "root_id": "u-manual"})
        return common.Dog(id="u-manual", kind=common.KIND_USER, name="Dog Days", tagline="", hound=h,
                          owner_user_id=7, status="running", root_id="u-manual")

    def _send(self, dog, market="moneyline"):
        from tests._hounds_user_fixtures import standard_rows
        return manual.record(dog, 7, "evt0001", market, now=NOW, ledger=self.manual_ledger,
                             rule_ledger=self.ledger, rows_for=lambda date, sports: iter(standard_rows()))

    def test_a_manual_send_that_contradicts_an_open_rule_bet_is_refused_in_plain_words(self):
        # the engine's own ticket is the home spread; the dog's rule would back Boston (the away side) on the moneyline
        HashChainLedger(self.ledger).append({
            "kind": user_engine.KIND_BET, "hound_id": "u-manual", "event_id": "evt0001", "bet_id": "b-open",
            "market": "spread", "side": "home", "slate_date": F.DATE})
        with self.assertRaises(manual.ManualError) as caught:
            self._send(self._dog())
        self.assertEqual(str(caught.exception), "already on the other side of this game")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(manual.read_all(self.manual_ledger), [])

    def test_a_manual_send_that_contradicts_an_earlier_manual_ticket_is_refused_too(self):
        HashChainLedger(self.manual_ledger).append({
            "kind": user_engine.KIND_BET, "hound_id": "u-manual", "event_id": "evt0001", "bet_id": "m-earlier",
            "market": "spread", "side": "home", "slate_date": F.DATE, "manual": True,
            "recorded_utc": "2026-10-20T21:00:00Z"})
        with self.assertRaises(manual.ManualError) as caught:
            self._send(self._dog())
        self.assertEqual(str(caught.exception), "already on the other side of this game")
        self.assertEqual(len(manual.read_all(self.manual_ledger)), 1)

    def test_the_preview_does_not_offer_the_second_ticket_on_a_side_it_already_covers(self):
        dog = self._dog(markets=["moneyline", "spread"], side_rule="underdog", price_min=-199, price_max=1000)
        with self.assertRaises(manual.ManualError) as caught:
            self._send(dog, "spread")                          # Boston's moneyline outranks Boston's spread
        self.assertEqual(caught.exception.code, "not_a_pick")

    def test_a_manual_ticket_and_the_opposite_rule_ticket_cannot_both_stand(self):
        rows = [{"kind": "hound_user_bet", "hound_id": "u-manual", "event_id": "evt0001", "market": "moneyline",
                 "side": "away"}]
        book = one_side.Book.from_rows(rows)
        self.assertEqual(book.refusal("u-manual", "evt0001", "spread", "home"), one_side.CODE_OTHER)

    def test_a_manual_send_with_nothing_on_the_game_still_records(self):
        ticket = self._send(self._dog())
        self.assertEqual(ticket["market"], "moneyline")


class OneGameManyNames(_Base):
    """The same game can arrive under two event ids (the odds feed re-issued one for the 2026-10-15 Guardians at
    Rays game, whose start moved; a provider could spell the id another way). The guard names a game by its
    event id, its MLB game_pk, or its teams and exact start, so a second id cannot hold the other side."""

    def reissued(self, start_shift=None) -> list:
        rows = []
        for r in nba_rows():
            r = dict(r, event_id="nba0001-reissued")
            if start_shift:
                r["commence_time"] = start_shift
            rows.append(r)
        return rows

    def test_the_other_side_under_a_second_event_id_of_the_same_game_is_refused(self):
        self.run_day([dog([nba_rule(markets=["moneyline"], side="away")])], nba_rows())
        report = self.run_day([dog([nba_rule(markets=["spread"], side="home")])], self.reissued())
        self.assertEqual([(b["event_id"], b["market"]) for b in self.bets()], [("nba0001", "moneyline")])
        self.assertEqual(report["skipped"].get(one_side.CODE_DEAD), 1)

    def test_one_run_that_sees_both_ids_takes_one_bet_not_two(self):
        h = dog([nba_rule(markets=["moneyline"], side="away"), nba_rule(markets=["spread"], side="home")])
        self.run_day([h], nba_rows() + self.reissued())
        self.assertEqual(len(self.bets()), 1, [(b["event_id"], b["market"]) for b in self.bets()])

    def test_the_same_side_under_the_second_id_is_not_a_second_ticket(self):
        h = dog([nba_rule(markets=["moneyline"], side="away")])
        self.run_day([h], nba_rows())
        report = self.run_day([h], self.reissued())
        self.assertEqual(len(self.bets()), 1)
        self.assertEqual(report["skipped"].get(one_side.CODE_SAME), 1)

    def test_a_different_start_with_no_game_pk_is_a_different_game(self):
        # two real games of one pair (a doubleheader) never start at the same instant; without a pk to say
        # otherwise the guard does not merge them
        self.run_day([dog([nba_rule(markets=["moneyline"], side="away")])], nba_rows())
        moved = self.reissued(start_shift="2026-10-20T23:20:00Z")
        before = len(self.bets())
        self.run_day([dog([nba_rule(markets=["spread"], side="home")])], moved)
        self.assertEqual(len(self.bets()), before + 1)

    def test_one_game_pk_is_one_game_even_when_the_start_moved(self):
        book = one_side.Book.from_rows([
            {"kind": "hound_user_bet", "hound_id": "h", "event_id": "id-1", "market": "moneyline", "side": "away",
             "sport": "MLB", "home_team": "Tampa Bay Rays", "away_team": "Cleveland Guardians",
             "commence_time": "2026-10-15T22:00:00Z", "game_pk": "849818"}])
        later = {"sport": "MLB", "home_team": "Tampa Bay Rays", "away_team": "Cleveland Guardians",
                 "commence_time": "2026-10-15T17:00:00Z", "game_pk": "849818"}
        self.assertEqual(book.refusal("h", "id-2", "spread", "home", None, -1.5, game=later), one_side.CODE_DEAD)
        other_game = dict(later, game_pk="849819", commence_time="2026-10-15T21:00:00Z")
        self.assertIsNone(book.refusal("h", "id-3", "spread", "home", None, -1.5, game=other_game))

    def test_a_spelling_of_the_start_and_the_teams_does_not_split_a_game(self):
        book = one_side.Book.from_rows([
            {"kind": "hound_user_bet", "hound_id": "h", "event_id": "a", "market": "total", "side": "over",
             "sport": "NBA", "home_team": "New York  Knicks", "away_team": "Philadelphia 76ers",
             "commence_time": "2026-10-21T00:00:00Z"}])
        again = {"sport": "NBA", "home_team": "new york knicks", "away_team": "PHILADELPHIA 76ERS",
                 "commence_time": "2026-10-20T20:00:00-04:00"}
        self.assertEqual(book.refusal("h", "b", "total", "under", game=again), one_side.CODE_OTHER)


class EngineAfterManual(_Base):
    """The tap and the engine hold each other off in both orders: manual.record already reads the rule ledger;
    the engine now reads the manual ledger beside it."""

    def test_an_owner_ticket_on_one_side_stops_the_engine_adding_the_other(self):
        manual_ledger = os.path.join(os.path.dirname(self.ledger), user_engine.MANUAL_LEDGER_NAME)
        HashChainLedger(manual_ledger).append({
            "kind": user_engine.KIND_BET, "hound_id": "u-jsmooth", "event_id": "nba0001", "bet_id": "m-1",
            "market": "spread", "side": "home", "line": -4.5, "slate_date": F.DATE, "manual": True,
            "recorded_utc": "2026-10-20T21:00:00Z"})
        report = self.run_day([dog([nba_rule(markets=["moneyline"], side="away")])], nba_rows())
        self.assertEqual(self.bets(), [])
        self.assertEqual(report["skipped"].get(one_side.CODE_DEAD), 1)

    def test_another_dogs_manual_ticket_does_not_matter(self):
        manual_ledger = os.path.join(os.path.dirname(self.ledger), user_engine.MANUAL_LEDGER_NAME)
        HashChainLedger(manual_ledger).append({
            "kind": user_engine.KIND_BET, "hound_id": "u-someone-else", "event_id": "nba0001", "bet_id": "m-2",
            "market": "spread", "side": "home", "line": -4.5, "slate_date": F.DATE, "manual": True,
            "recorded_utc": "2026-10-20T21:00:00Z"})
        self.run_day([dog([nba_rule(markets=["moneyline"], side="away")])], nba_rows())
        self.assertEqual(len(self.bets()), 1)

    def test_the_manual_ledger_follows_the_rule_ledger_it_sits_beside(self):
        self.assertEqual(os.path.basename(user_engine.manual_ledger_path(self.ledger)), "hounds_manual_v1.jsonl")
        self.assertEqual(os.path.dirname(user_engine.manual_ledger_path(self.ledger)), os.path.dirname(self.ledger))


class TheRuleIsWritten(unittest.TestCase):
    def test_the_voice_doc_says_it_in_one_sentence(self):
        text = open(os.path.join(os.path.dirname(__file__), "..", "docs", "VOICE.md"), encoding="utf-8").read()
        self.assertIn("A hound takes one side per game.", text)


if __name__ == "__main__":
    unittest.main()
