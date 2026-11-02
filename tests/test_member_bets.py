"""src/hounds/member_bets.py: place -> settle -> record, on the member ledger, with fixtures for an NHL moneyline,
a tennis moneyline and an NHL total (plus a live bet and a bet on a game that is not on our board).

No FastAPI needed: this runs on Linux CI. Nothing reads a live store; the board rows and the scores are injected."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from src.hounds import member_bets as mb
from src.hounds import user_engine, user_settle
from src.ledger.chain import HashChainLedger
from src.notify import alerts
from src.pipeline import allsports_scores as S
from tests._hounds_user_fixtures import BOOKS, START, board_rows, utc

OWNER, OTHER = 7, 8
NHL_EVENT, TENNIS_EVENT = "nhl-evt-1", "ten-evt-1"
NHL_HOME, NHL_AWAY = "Boston Bruins", "Toronto Maple Leafs"
T_HOME, T_AWAY = "Carlos Alcaraz", "Jannik Sinner"
BOARD_AT = "2026-10-20T21:05:00Z"
PLACED = utc("2026-10-20T21:30:00Z")             # 100 minutes before the 23:10Z start
SETTLE_AT = utc("2026-10-21T04:00:00Z")          # well after every game


def rows():
    out = []
    out += board_rows(BOARD_AT, event_id=NHL_EVENT, home=NHL_HOME, away=NHL_AWAY, sport="nhl",
                      moneyline=[(b, -140, 120) for b in BOOKS],
                      total=(6.5, [(b, -110, -110) for b in BOOKS]))
    out += board_rows(BOARD_AT, event_id=TENNIS_EVENT, home=T_HOME, away=T_AWAY, sport="tennis",
                      moneyline=[(b, 130, -150) for b in BOOKS])
    return out


def live_rows():
    return rows() + board_rows("2026-10-20T23:25:00Z", event_id=NHL_EVENT, home=NHL_HOME, away=NHL_AWAY,
                               sport="nhl", moneyline=[(b, -300, 240) for b in BOOKS])


def rows_for(_date, _sports):
    return iter(rows())


def score(event_id, home, away, home_score, away_score, key="icehockey_nhl"):
    return S.score_row({"id": event_id, "sport_key": key, "commence_time": START, "completed": True,
                        "home_team": home, "away_team": away, "last_update": START,
                        "scores": [{"name": home, "score": str(home_score)},
                                   {"name": away, "score": str(away_score)}]},
                       "2026-10-21T03:00:00Z", key)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = str(Path(self._tmp.name) / "hounds_member_bets_v1.jsonl")

    def place(self, owner=OWNER, **kw):
        base = dict(event_id=NHL_EVENT, market="moneyline", side="home", stake_units=1.0,
                    now=PLACED, ledger=self.ledger, rows_for=rows_for)
        base.update(kw)
        return mb.place_bet(owner, **base)

    def settle(self, results, close=lambda b: None):
        return mb.settle(ledger=self.ledger, now=SETTLE_AT, close_fn=close, allsports_results=results)

    def view(self, owner=OWNER, now=SETTLE_AT):
        return mb.member_view(owner, now=now, ledger=self.ledger)


class Placing(Base):
    def test_nhl_moneyline_takes_the_board_average_when_no_price_is_typed(self):
        row = self.place(stake_units=2.0)
        self.assertEqual((row["sport"], row["market"], row["side"], row["price"]),
                         ("NHL", "moneyline", "home", -140))
        self.assertEqual((row["owner_user_id"], row["hound_id"], row["source"], row["kind"]),
                         (OWNER, None, "member", user_engine.KIND_BET))
        self.assertEqual((row["stake_units"], row["live"], row["price_source"]), (2.0, False, "board"))
        self.assertEqual(row["n_books"], len(BOOKS))
        self.assertTrue(row["bet_id"].startswith("mb-"))
        self.assertEqual(row["slate_date"], "2026-10-20")

    def test_a_typed_price_is_the_price_the_bet_is_graded_at(self):
        row = self.place(event_id=TENNIS_EVENT, side="away", price=-145)
        self.assertEqual((row["sport"], row["price"], row["best_price"], row["price_source"]),
                         ("TENNIS", -145, -145, "typed"))
        self.assertEqual(row["board_price_average"], -150)

    def test_total_takes_the_board_line(self):
        row = self.place(market="total", side="over")
        self.assertEqual((row["line"], row["price"], row["selection"]), (6.5, -110, "Over 6.5"))

    def test_a_price_that_is_not_on_the_board_must_be_typed(self):
        with self.assertRaises(mb.BetError) as ctx:
            self.place(event_id=TENNIS_EVENT, market="total", side="over", line=20.5)
        self.assertIn("Type the price", str(ctx.exception))
        row = self.place(event_id=TENNIS_EVENT, market="total", side="over", line=20.5, price=-105)
        self.assertEqual((row["line"], row["price"]), (20.5, -105))

    def test_unknown_game_is_a_404_with_a_plain_sentence(self):
        with self.assertRaises(mb.BetError) as ctx:
            self.place(event_id="nope")
        self.assertEqual(ctx.exception.status, 404)
        self.assertIn("by hand", str(ctx.exception))

    def test_bad_inputs_are_refused(self):
        for kw in ({"price": 50}, {"price": 1_000_000}, {"price": float("nan")}, {"price": 120.5},
                   {"stake_units": 0.1}, {"stake_units": 11}, {"stake_units": float("inf")},
                   {"note": "x" * 141}, {"market": "prop"}, {"side": "over"}):
            with self.subTest(kw=kw):
                with self.assertRaises(mb.BetError):
                    self.place(**kw)
        self.assertEqual(HashChainLedger(self.ledger).read(), [])

    def test_stake_bounds_are_inclusive(self):
        self.place(stake_units=0.25)
        self.place(event_id=TENNIS_EVENT, stake_units=10)

    def test_one_side_per_game_per_member(self):
        self.place(side="home")
        with self.assertRaises(mb.BetError) as ctx:
            self.place(side="away")
        self.assertEqual(ctx.exception.status, 409)
        with self.assertRaises(mb.BetError):          # the same side twice is a second bet on a side already held
            self.place(side="home")
        self.place(market="total", side="over")        # a total is its own slot
        self.place(owner=OTHER, side="away")           # another member is not held to this member's side

    def test_a_removed_bet_frees_the_side(self):
        first = self.place(side="home")
        mb.void_bet(OWNER, first["bet_id"], now=PLACED, ledger=self.ledger)
        self.place(side="away")

    def test_a_live_bet_is_flagged_and_priced_on_the_live_board(self):
        now = utc("2026-10-20T23:40:00Z")
        row = mb.place_bet(OWNER, event_id=NHL_EVENT, market="moneyline", side="away", stake_units=1, now=now,
                           ledger=self.ledger, rows_for=lambda d, s: iter(live_rows()))
        self.assertTrue(row["live"])
        self.assertLess(user_engine._utc(row["commence_time"]), user_engine._utc(row["placed_utc"]))
        self.assertEqual(row["price"], 240)

    def test_a_game_long_over_is_refused(self):
        with self.assertRaises(mb.BetError) as ctx:
            self.place(now=utc("2026-10-21T12:00:00Z"))
        self.assertIn("over", str(ctx.exception))

    def test_a_stale_board_gives_no_prefill(self):
        info = mb.current_price(NHL_EVENT, "moneyline", "home", now=utc("2026-10-20T22:50:00Z"), rows_for=rows_for)
        self.assertEqual(info["price"], None)
        info = mb.current_price(NHL_EVENT, "moneyline", "home", now=PLACED, rows_for=rows_for)
        self.assertEqual((info["price"], info["n_books"]), (-140, len(BOOKS)))


class Voiding(Base):
    def test_void_before_the_start_appends_a_row_and_the_bet_is_never_graded(self):
        bet = self.place()
        before = len(HashChainLedger(self.ledger).read())
        mb.void_bet(OWNER, bet["bet_id"], now=PLACED + timedelta(minutes=5), ledger=self.ledger)
        rows_after = HashChainLedger(self.ledger).read()
        self.assertEqual(len(rows_after), before + 1)                       # appended, nothing edited or removed
        self.assertEqual(rows_after[0]["bet_id"], bet["bet_id"])
        self.assertTrue(rows_after[-1]["voided_by_member"])
        report = self.settle({NHL_EVENT: score(NHL_EVENT, NHL_HOME, NHL_AWAY, 4, 1)})
        self.assertEqual(report["considered"], 0)
        v = self.view()["bets"][0]
        self.assertEqual((v["status"], v["result"], v["can_void"]), ("removed", "VOID", False))
        self.assertEqual(self.view()["record"]["void"], 1)

    def test_void_after_the_start_is_refused_and_leaves_the_ledger_alone(self):
        bet = self.place()
        before = HashChainLedger(self.ledger).read()
        with self.assertRaises(mb.BetError) as ctx:
            mb.void_bet(OWNER, bet["bet_id"], now=utc("2026-10-20T23:11:00Z"), ledger=self.ledger)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(HashChainLedger(self.ledger).read(), before)

    def test_only_the_owner_can_void_and_a_voided_bet_cannot_be_voided_twice(self):
        bet = self.place()
        with self.assertRaises(mb.BetError) as ctx:
            mb.void_bet(OTHER, bet["bet_id"], now=PLACED, ledger=self.ledger)
        self.assertEqual(ctx.exception.status, 404)
        mb.void_bet(OWNER, bet["bet_id"], now=PLACED, ledger=self.ledger)
        with self.assertRaises(mb.BetError):
            mb.void_bet(OWNER, bet["bet_id"], now=PLACED, ledger=self.ledger)


class SettleAndRecord(Base):
    def test_place_settle_record_on_an_nhl_game_a_tennis_match_and_a_total(self):
        ml = self.place(side="home", stake_units=2.0)                                   # Bruins -140, wins 4-1
        tennis = self.place(event_id=TENNIS_EVENT, side="home", stake_units=1.0)        # Alcaraz +130, loses
        total = self.place(market="total", side="over", stake_units=0.5)                # over 6.5, 5 goals: loses
        results = {NHL_EVENT: score(NHL_EVENT, NHL_HOME, NHL_AWAY, 4, 1),
                   TENNIS_EVENT: score(TENNIS_EVENT, T_HOME, T_AWAY, 0, 1, "tennis_atp_test")}
        nhl_ml = lambda b: -150 if b["market"] == "moneyline" and b["sport"] == "NHL" else None  # noqa: E731
        with mock.patch.object(alerts, "emit_settled_safe") as alert:
            report = self.settle(results, close=nhl_ml)
        alert.assert_not_called()                                                       # a member knows what they bet
        self.assertEqual((report["considered"], report["graded"]), (3, 3))
        view = {b["id"]: b for b in self.view()["bets"]}
        win = 0.7143 * 2.0
        self.assertEqual((view[ml["bet_id"]]["result"], view[ml["bet_id"]]["status"]), ("WIN", "settled"))
        self.assertAlmostEqual(view[ml["bet_id"]]["units"], win, places=3)
        self.assertEqual((view[tennis["bet_id"]]["result"], view[tennis["bet_id"]]["units"]), ("LOSS", -1.0))
        self.assertEqual((view[total["bet_id"]]["result"], view[total["bet_id"]]["units"]), ("LOSS", -0.5))
        # CLV lands: the price got (-140) against an average close of -150.
        self.assertIsNotNone(view[ml["bet_id"]]["clv_pts"])
        self.assertEqual(view[ml["bet_id"]]["close_price"], -150)
        self.assertIsNone(view[tennis["bet_id"]]["clv_pts"])
        rec = self.view()["record"]
        self.assertEqual((rec["w"], rec["l"], rec["p"]), (1, 2, 0))
        self.assertAlmostEqual(rec["units"], win - 1.0 - 0.5, places=3)
        self.assertEqual((rec["stake_units"], rec["n_clv"]), (3.5, 1))
        self.assertEqual(self.view()["open"], 0)
        self.assertEqual(self.settle(results)["considered"], 0)                         # a second pass adds nothing
        self.assertTrue(HashChainLedger(self.ledger).verify().ok)

    def test_members_are_graded_separately(self):
        a = self.place(owner=OWNER, side="home")
        b = self.place(owner=OTHER, side="away")
        self.settle({NHL_EVENT: score(NHL_EVENT, NHL_HOME, NHL_AWAY, 4, 1)})
        self.assertEqual(self.view(OWNER)["bets"][0]["result"], "WIN")
        self.assertEqual(self.view(OTHER)["bets"][0]["result"], "LOSS")
        self.assertEqual([x["id"] for x in self.view(OWNER)["bets"]], [a["bet_id"]])
        self.assertEqual([x["id"] for x in self.view(OTHER)["bets"]], [b["bet_id"]])

    def test_an_unfinished_game_stays_open(self):
        self.place()
        self.settle({})
        v = self.view(now=PLACED)
        self.assertEqual((v["open"], v["bets"][0]["status"], v["bets"][0]["can_void"]), (1, "open", True))
        self.assertEqual(v["record"]["w"] + v["record"]["l"], 0)

    def test_a_live_bet_never_gets_a_closing_line_value(self):
        bet = mb.place_bet(OWNER, event_id=NHL_EVENT, market="moneyline", side="away", stake_units=1,
                           now=utc("2026-10-20T23:40:00Z"), ledger=self.ledger,
                           rows_for=lambda d, s: iter(live_rows()))
        called = []
        self.settle({NHL_EVENT: score(NHL_EVENT, NHL_HOME, NHL_AWAY, 1, 3)},
                    close=lambda b: called.append(b) or -100)
        self.assertEqual(called, [])
        v = self.view()["bets"][0]
        self.assertEqual((v["id"], v["live"], v["result"], v["clv_pts"]), (bet["bet_id"], True, "WIN", None))
        self.assertAlmostEqual(v["units"], 2.4, places=3)

    def test_the_default_close_reads_the_board(self):
        self.place()
        close = user_settle.make_close_fn(rows_for=lambda date, sport: rows())
        self.settle({NHL_EVENT: score(NHL_EVENT, NHL_HOME, NHL_AWAY, 4, 1)}, close=close)
        v = self.view()["bets"][0]
        self.assertEqual((v["close_price"], v["clv_pts"]), (-140, 0.0))

    def test_settle_with_no_ledger_yet_does_nothing(self):
        out = mb.settle(ledger=str(Path(self._tmp.name) / "none.jsonl"), now=SETTLE_AT)
        self.assertEqual(out["graded"], 0)


class NotOnOurBoard(Base):
    def test_manual_bet_is_unmatched_and_never_graded(self):
        row = mb.place_manual(OWNER, sport="tennis", game_text="Local Open final", side_text="Smith",
                              price=-120, stake_units=1.5, now=PLACED, ledger=self.ledger)
        self.assertEqual((row["status"], row["event_id"]), ("unmatched", None))
        report = self.settle({})
        self.assertEqual(report["considered"], 0)
        v = self.view(now=PLACED)
        self.assertEqual((v["open"], v["bets"][0]["status"], v["bets"][0]["kind"]), (1, "unmatched", "manual"))
        self.assertEqual(v["record"]["w"] + v["record"]["l"], 0)

    def test_manual_validation_and_a_short_window_to_remove_it(self):
        with self.assertRaises(mb.BetError):
            mb.place_manual(OWNER, sport="curling", game_text="x", side_text="y", stake_units=1,
                            ledger=self.ledger)
        with self.assertRaises(mb.BetError):
            mb.place_manual(OWNER, sport="NHL", game_text="", side_text="y", stake_units=1, ledger=self.ledger)
        row = mb.place_manual(OWNER, sport="NHL", game_text="A at B", side_text="A", stake_units=1, now=PLACED,
                              ledger=self.ledger)
        with self.assertRaises(mb.BetError):
            mb.void_bet(OWNER, row["bet_id"], now=PLACED + timedelta(hours=2), ledger=self.ledger)
        mb.void_bet(OWNER, row["bet_id"], now=PLACED + timedelta(minutes=10), ledger=self.ledger)
        self.assertEqual(self.view(now=PLACED)["bets"][0]["status"], "removed")


class LedgerPath(unittest.TestCase):
    def test_default_sits_beside_the_app_database_and_the_env_wins(self):
        from src.appstate import users as users_store
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "app.db"
            with mock.patch.object(users_store, "db_path", lambda: db), \
                    mock.patch.dict(os.environ, {mb.ENV_LEDGER: "", user_engine.ENV_LEDGER: ""}):
                self.assertEqual(Path(mb.ledger_path()), Path(tmp) / "hounds_member_bets_v1.jsonl")
                self.assertEqual(Path(user_engine.ledger_path()).parent, Path(mb.ledger_path()).parent)
            with mock.patch.dict(os.environ, {mb.ENV_LEDGER: "/x/y.jsonl"}):
                self.assertEqual(mb.ledger_path(), "/x/y.jsonl")
            self.assertEqual(mb.ledger_path("/a/b.jsonl"), "/a/b.jsonl")

    def test_a_shadow_hound_ledger_gets_its_own_member_ledger(self):
        self.assertEqual(Path(mb.ledger_beside("/t/hounds_user_v1.jsonl")), Path("/t/hounds_member_bets_v1.jsonl"))


class Copy(Base):
    def test_no_banned_words_in_member_facing_errors(self):
        banned = re.compile(r"\b(edge|lock|beta|new|paper|promise)\b", re.I)
        msgs = []
        for kw in ({"price": 50}, {"stake_units": 99}, {"note": "x" * 200}, {"market": "x"}, {"side": "over"},
                   {"event_id": "nope"}, {"now": utc("2026-10-21T12:00:00Z")}):
            try:
                self.place(**kw)
            except mb.BetError as exc:
                msgs.append(str(exc))
        self.place(side="home")
        try:
            self.place(side="away")
        except mb.BetError as exc:
            msgs.append(str(exc))
        self.assertGreaterEqual(len(msgs), 8)
        for m in msgs:
            self.assertIsNone(banned.search(m), m)
        v = self.view(now=PLACED)["bets"][0]
        self.assertIsNone(banned.search(" ".join(str(x) for x in v.values())))


if __name__ == "__main__":
    unittest.main()
