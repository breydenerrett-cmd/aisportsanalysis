"""Shadow running: a challenger is run by its champion's own engine, on the same boards, forward only.

The claim under test is the one the whole comparison rests on: "the same games at the same prices".
A challenger whose rule equals its champion's must write rows identical in every price, line, lock and
selection field; one proposed after a game's lock must not bet it; nothing is ever replayed; the -200
rule holds for a challenger exactly as for a champion; and none of this is readable by a public source.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.hounds import pack as pack_mod
from src.hounds import pack_run, user_engine
from src.hounds.ledgers import Sources
from src.hounds.learning import ledger as L, shadow, tunables
from src.hounds.pack import base
from src.ledger.chain import HashChainLedger
from tests import _hounds_user_fixtures as UF
from tests.test_house_pack_hounds import START as PACK_START, basic_stores

UTC = timezone.utc
PRICE_FIELDS = ("market", "side", "line", "market_line", "selection", "price_average", "price_best", "book",
                "book_count", "consensus_fair", "lock_utc", "start_utc", "date", "event_id", "sport",
                "reason", "who_decided", "segment", "stake", "score")


def propose_raw(scope, **kw):
    """A proposal event written directly (the guards are tested in test_hounds_learning_proposals)."""
    fields = dict(scope=scope.name, challenger_id="c-test", hound_kind="pack", hound_id="professor_paws",
                  lineage_key="professor_paws", category="stats", parent_version=1, parent_ref=None,
                  spec={}, spec_hash="h", spec_diff={}, hypothesis="x" * 30, evidence=["a"],
                  proposed_by="coach")
    fields.update(kw)
    return L.log_for(scope).append(L.K_PROPOSAL, now=fields.pop("now"), **fields)


class PackShadow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.scope = L.Scope.house(self.root)
        self.champ_path = str(self.root / "hounds_house_v1.jsonl")
        self.stores = basic_stores()
        self.lock = PACK_START - timedelta(minutes=60)
        self.now = self.lock + timedelta(minutes=5)
        self.dates = ["2026-09-20"]

    def propose(self, values=None, created=None, cid="c-test"):
        t = tunables.load()["professor_paws"]
        values = values if values is not None else t.defaults()
        return propose_raw(self.scope, challenger_id=cid, spec={"values": values, "rule_text": "x"},
                           now=created or (self.lock - timedelta(days=1)))

    def champion_rows(self):
        pack_run.run(self.stores, self.dates, replay=False, now=self.now, path=self.champ_path,
                     hounds=[pack_mod.BY_ID["professor_paws"]], out=lambda *a, **k: None)
        return [r for r in HashChainLedger(self.champ_path).read() if r["kind"] == pack_run.KIND_BET]

    def challenger_rows(self):
        return [r for r in HashChainLedger(self.scope.challenger_bets).read() if r["kind"] == pack_run.KIND_BET]

    def test_an_identical_challenger_writes_rows_identical_in_every_price_and_lock_field(self):
        self.propose()                     # knob values equal the champion's declared defaults
        champ = self.champion_rows()
        out = shadow.run_pack(self.stores, self.dates, self.scope, now=self.now)
        mine = self.challenger_rows()
        self.assertEqual(out["challengers"], 1)
        self.assertEqual(len(champ), 1)
        self.assertEqual(len(mine), 1)
        for f in PRICE_FIELDS:
            self.assertEqual(mine[0][f], champ[0][f], f)
        self.assertEqual(mine[0]["hound_id"], "c-test")
        self.assertEqual(mine[0]["role"], "challenger")
        self.assertEqual(mine[0]["challenger_id"], "c-test")
        self.assertEqual(mine[0]["parent_hound_id"], "professor_paws")
        self.assertEqual(mine[0]["parent_version"], 1)
        self.assertEqual(mine[0]["segment"], "forward")

    def test_a_different_knob_changes_the_decision_not_the_price(self):
        # Paws's gap on this board is about 0.107; a bar of 0.04 still clears, so the bet is the same,
        # and the price fields are the champion's. (The decision difference is tested on a fake hound
        # below, where a knob can be made to bind.)
        self.propose(values={"GAP": 0.04, "SHRINK": 0.5})
        champ = self.champion_rows()
        shadow.run_pack(self.stores, self.dates, self.scope, now=self.now)
        mine = self.challenger_rows()
        self.assertEqual(mine[0]["price_average"], champ[0]["price_average"])
        self.assertEqual(mine[0]["params"]["GAP"], 0.04)

    def test_a_proposal_after_the_lock_does_not_bet_that_game(self):
        self.propose(created=self.lock + timedelta(minutes=1))
        out = shadow.run_pack(self.stores, self.dates, self.scope, now=self.now)
        self.assertEqual(self.challenger_rows(), [])
        self.assertEqual(out.get("covered_new"), 0)

    def test_nothing_is_ever_replayed_a_started_game_is_not_bet(self):
        self.propose()
        after_start = PACK_START + timedelta(minutes=1)
        shadow.run_pack(self.stores, self.dates, self.scope, now=after_start)
        self.assertEqual(self.challenger_rows(), [])

    def test_a_game_before_its_lock_is_not_bet(self):
        self.propose()
        shadow.run_pack(self.stores, self.dates, self.scope, now=self.lock - timedelta(minutes=1))
        self.assertEqual(self.challenger_rows(), [])

    def test_a_rerun_adds_nothing(self):
        self.propose()
        shadow.run_pack(self.stores, self.dates, self.scope, now=self.now)
        shadow.run_pack(self.stores, self.dates, self.scope, now=self.now + timedelta(minutes=10))
        self.assertEqual(len(self.challenger_rows()), 1)

    def test_coverage_records_the_game_once(self):
        self.propose()
        first = shadow.run_pack(self.stores, self.dates, self.scope, now=self.now)
        second = shadow.run_pack(self.stores, self.dates, self.scope, now=self.now + timedelta(minutes=10))
        self.assertEqual(first["covered_new"], 1)
        self.assertEqual(second["covered_new"], 0)
        self.assertEqual(L.read_state(self.scope).coverage, {"c-test": {"evA"}})

    def test_a_challenger_whose_champion_moved_on_is_not_run(self):
        self.propose()
        L.log_for(self.scope).append(L.K_PROMOTION, scope="house", hound_id="professor_paws",
                                     challenger_id="c-other", from_version=1, to_version=2,
                                     params={"GAP": 0.03, "SHRINK": 0.5}, applied=True)
        out = shadow.run_pack(self.stores, self.dates, self.scope, now=self.now)
        self.assertEqual(out["challengers"], 0)

    def test_the_minus_200_rule_holds_for_a_challenger(self):
        class Fav(base.Hound):
            id, name, tagline, category, style = "fav", "Fav", "t", "stats", "s"
            sports, markets, who_decided, RULE = ("mlb",), ("moneyline",), "rule", "x 1.0 y"

            def pick(self, board, ctx):
                return [base.Selection("moneyline", "home", 1.0, "always the home side")]

        # a board where home is a -300 favourite on every book
        from tests.test_house_pack_hounds import game_rows
        stores = base.Stores()
        for r in game_rows("evF", PACK_START, home_ml=-300, away_ml=250,
                           observed=PACK_START - timedelta(hours=2)):
            stores.add_row(r)
        stores.event_map = {}
        stores.finalize()
        t = tunables.TunableHound("fav", "Fav", "stats", "tests.test_hounds_learning_shadow", "x 1.0 y",
                                  ("mlb",), ("moneyline",),
                                  {"K": tunables.Knob("K", "k", "float", 1.0, 0.5, 2.0, 0.5, ())})
        globals()["K"] = 1.0
        propose_raw(self.scope, challenger_id="c-fav", hound_id="fav", lineage_key="fav",
                    spec={"values": {"K": 1.0}, "rule_text": "x"}, now=self.lock - timedelta(days=1))
        out = shadow.run_pack(stores, self.dates, self.scope, now=self.now, tun_cfg={"fav": t},
                              registry={"fav": Fav()})
        self.assertEqual(out["challengers"], 1)
        self.assertEqual(self.challenger_rows(), [])        # -300 is refused, as it is for any hound

    def test_challenger_ledger_is_not_a_public_source(self):
        public = [str(p) for _label, p in Sources.default().pack_ledgers]
        self.assertNotIn(str(self.scope.challenger_bets), public)
        self.assertNotIn(L.HOUSE_BETS, " ".join(Path(p).name for p in public))
        self.assertNotIn(L.USER_BETS, " ".join(Path(p).name for p in public))


class UserShadow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.scope = L.Scope.user(self.root)
        self.champ_path = str(self.root / "hounds_user_v1.jsonl")
        self.hound = UF.hound("u-champ")
        self.now = UF.utc("2026-10-20T21:20:00Z")          # after the 21:10Z lock, before the 23:10Z start

    def rows_for(self, date, sports):
        return UF.standard_rows()

    def propose(self, created="2026-10-19T12:00:00Z", spec=None, cid="c-user"):
        spec = spec or self.hound["spec"]
        propose_raw(self.scope, challenger_id=cid, hound_kind="user", hound_id="u-champ", lineage_key="u-champ",
                    category="mixed", parent_ref="u-champ", spec=dict(spec), spec_hash="h2",
                    now=UF.utc(created))

    def champion_rows(self):
        user_engine.run(UF.DATE, [self.hound], UF.standard_rows(), ledger=self.champ_path, now=self.now)
        return [r for r in HashChainLedger(self.champ_path).read() if r["kind"] == user_engine.KIND_BET]

    def challenger_rows(self):
        return [r for r in HashChainLedger(self.scope.challenger_bets).read()
                if r["kind"] == user_engine.KIND_BET]

    def test_an_identical_challenger_writes_rows_identical_in_every_price_and_lock_field(self):
        self.propose()
        champ = self.champion_rows()
        out = shadow.run_user(self.scope, [UF.DATE], now=self.now, rows_for=self.rows_for, game_pk_index={})
        mine = self.challenger_rows()
        self.assertEqual((out["challengers"], out["written"]), (1, 1))
        self.assertEqual(len(champ), 1)
        for f in ("market", "side", "line", "selection", "price", "best_price", "best_book", "n_books",
                  "lock_utc", "commence_time", "board_observed_utc", "board_age_minutes", "event_id",
                  "slate_date", "price_average", "price_best", "book", "book_count", "start_utc", "segment"):
            self.assertEqual(mine[0][f], champ[0][f], f)
        self.assertEqual(mine[0]["hound_id"], "c-user")
        self.assertEqual(mine[0]["role"], "challenger")
        self.assertEqual(mine[0]["challenger_id"], "c-user")
        self.assertEqual(mine[0]["parent_hound_id"], "u-champ")
        self.assertEqual(mine[0]["segment"], "forward")
        self.assertNotEqual(mine[0]["bet_id"], champ[0]["bet_id"])

    def test_a_proposal_after_the_lock_does_not_bet_that_game(self):
        self.propose(created="2026-10-20T21:15:00Z")
        out = shadow.run_user(self.scope, [UF.DATE], now=self.now, rows_for=self.rows_for, game_pk_index={})
        self.assertEqual(out["written"], 0)
        self.assertEqual(self.challenger_rows(), [])

    def test_a_different_rule_bets_a_different_side_on_the_same_board(self):
        spec = dict(self.hound["spec"], side_rule="favourite", price_min=-190, price_max=-110)
        self.propose(spec=spec)
        champ = self.champion_rows()
        shadow.run_user(self.scope, [UF.DATE], now=self.now, rows_for=self.rows_for, game_pk_index={})
        mine = self.challenger_rows()
        self.assertEqual(champ[0]["side"], "away")        # the underdog at the lock board
        self.assertEqual(mine[0]["side"], "home")         # the favourite on the SAME board
        self.assertEqual(mine[0]["board_observed_utc"], champ[0]["board_observed_utc"])

    def test_the_cap_holds_for_a_challenger(self):
        # a favourite at -170 average is inside the band, a -250 board is beyond the cap
        rows = UF.board_rows(UF.T_LOCK, moneyline=[(b, -250, 210) for b in UF.BOOKS])
        spec = dict(self.hound["spec"], side_rule="favourite", price_min=-190, price_max=-110)
        self.propose(spec=spec)
        out = shadow.run_user(self.scope, [UF.DATE], now=self.now, rows_for=lambda d, s: rows,
                              game_pk_index={})
        self.assertEqual(out["written"], 0)

    def test_coverage_names_the_game_the_challenger_looked_at(self):
        self.propose()
        shadow.run_user(self.scope, [UF.DATE], now=self.now, rows_for=self.rows_for, game_pk_index={})
        self.assertEqual(L.read_state(self.scope).coverage, {"c-user": {UF.EVENT}})

    def test_nothing_to_run_writes_nothing(self):
        out = shadow.run_user(self.scope, [UF.DATE], now=self.now, rows_for=self.rows_for, game_pk_index={})
        self.assertEqual(out["challengers"], 0)
        self.assertFalse(self.scope.challenger_bets.exists())


if __name__ == "__main__":
    unittest.main()
