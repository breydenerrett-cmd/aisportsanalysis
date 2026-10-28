"""The Learner: a house hound with no starting rules that bets small and wide on paper and logs what it knew.

Covers the config entry and its copy, the point-in-time features (and that nothing observed after the lock can reach them), the
draw (one side per game, never -200 or worse, the daily cap from config, idempotent), the runner wiring, the focus an owner
applies, and the phase-2 learn step: it refuses under 200 settled bets, trains only before the cutoff, tests forward, proposes
and never applies. Plain stdlib; nothing here needs FastAPI, a key or a network.
"""

from __future__ import annotations

import json
import os
import random
import re
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.ai import router as R
from src.hounds import ai_defs, ai_runner, house, learner, pack_run, pack_settle
from src.hounds.learner import features as feat
from src.hounds.learner import learn
from src.hounds.learner import state as lstate
from src.hounds.pack import base, learner_hound
from src.ledger.chain import HashChainLedger
from tests.test_ai_router import Clock
from tests.test_house_pack_hounds import START, T, basic_stores, game_rows, mlb_game

ROOT = Path(__file__).resolve().parents[1]
LOCKED = START - timedelta(minutes=30)
UTC = timezone.utc
DOG = re.compile(r"\bdog", re.I)
BANNED = re.compile(r"\b(beta|new)\b|guarantee|sure thing|beats the market|profit|edge", re.I)


def entry(**over):
    e = dict(ai_defs.entry_for("learner"))
    e.update(over)
    return e


def hound(**over):
    return learner_hound.LearnerHound(entry(**over), now_fn=lambda: LOCKED)


def ctx_board(stores=None, eid="evA"):
    stores = stores or basic_stores()
    ctx = base.build_context(stores, eid)
    return stores, ctx, base.lock_board(stores, ctx)


class ConfigAndCopyTests(unittest.TestCase):
    def test_the_house_entry_has_no_rules_a_cap_of_fifty_and_the_minus_200_band(self):
        e = ai_defs.entry_for("learner")
        self.assertEqual((e["category"], e["family"], e["who_decided"], e["providers"]), ("learner", "learner", "rule", []))
        self.assertEqual((e["max_per_day"], e["price_band"]), (50, [-199, 400]))
        self.assertLessEqual(e["stake_units"], 0.25)
        from src.hounds.contract import CATEGORIES

        self.assertIn("learner", CATEGORIES)
        self.assertIn("learner", ai_defs.ids())

    def test_it_is_listed_publicly_and_not_built_as_a_model_hound(self):
        defs = house.definitions(ROOT / "config" / "house_hounds.json", ROOT / "config" / "house_pack.json",
                                 ROOT / "config" / "desk_hounds.json", ROOT / "config" / "ai_hounds.json")
        d = next(x for x in defs if x["id"] == "learner")
        self.assertEqual((d["category"], d["name"]), ("learner", "The Learner"))
        from src.hounds.pack import ai_hounds

        runtime = mock.Mock()
        self.assertNotIn("learner", [h.id for h in ai_hounds.build_hounds(runtime)])

    def test_user_facing_copy_never_says_dog_beta_new_or_a_profit_claim(self):
        e = ai_defs.entry_for("learner")
        texts = [e["name"], e["tagline"], e["rule_text"], e["style"]] + [e["persona"][k] for k in ("bio", "catchphrase", "epitaph", "verb")]
        texts += e["persona"]["roasts"] + e["persona"]["brags"]
        texts += [learner.EXPERIMENTAL_LINE, learner.HONESTY, learner.NOT_ENOUGH]
        texts += list(feat.KIND_WORDS.values()) + [feat.segment_text(("nhl", "moneyline", k, "+100 to +180")) for k in feat.KIND_WORDS]
        for t in texts:
            self.assertIsNone(DOG.search(t), t)
            self.assertIsNone(BANNED.search(t.replace("no edge or profit", "")), t)
        # the honest framing is in the entry itself
        self.assertIn("unproven", e["rule_text"].lower())
        self.assertIn("never a promise", e["tagline"])

    def test_the_mascot_is_a_small_flat_svg_in_the_site_colours(self):
        path = ROOT / "web" / "img" / "learner-hound.svg"
        raw = path.read_bytes()
        self.assertLess(len(raw), 4096)
        text = raw.decode("utf-8")
        tokens = (ROOT / "web" / "css" / "tokens.css").read_text(encoding="utf-8").upper()
        colours = set(re.findall(r"#[0-9A-F]{6}", text.upper()))
        self.assertTrue(colours)
        for c in colours:
            self.assertIn(c, tokens, c)
        self.assertNotIn("<script", text.lower())
        self.assertNotIn("gradient", text.lower())          # flat


class FeatureTests(unittest.TestCase):
    def test_a_moneyline_bet_has_about_thirty_frozen_features(self):
        _, ctx, board = ctx_board()
        f = feat.build(ctx, board, "moneyline", "away", written=LOCKED)
        self.assertEqual(set(f), set(feat.FEATURE_NAMES))
        self.assertGreaterEqual(len(f), 20)
        self.assertEqual((f["sport"], f["market"], f["side"], f["role"], f["venue"]), ("mlb", "moneyline", "away", "underdog", "away"))
        self.assertEqual((f["band"], f["books"], f["hours_to_start"]), ("+100 to +180", 5, 0.5))
        self.assertEqual((f["day_of_week"], f["month"]), ("sun", 9))
        self.assertGreater(f["break_even"], 0)

    def test_a_total_has_no_role_or_venue_and_a_spread_is_signed_for_the_pick(self):
        _, ctx, board = ctx_board()
        t = feat.build(ctx, board, "total", "over", written=LOCKED)
        self.assertEqual((t["role"], t["venue"], t["line"]), (None, None, 8.5))
        home = feat.build(ctx, board, "spread", "home", written=LOCKED)
        away = feat.build(ctx, board, "spread", "away", written=LOCKED)
        self.assertEqual((home["line"], away["line"]), (-1.5, 1.5))

    def test_move_since_the_open_comes_from_the_earlier_capture(self):
        _, ctx, board = ctx_board()
        stores = basic_stores()
        opened = feat.open_market_board(stores.quotes_by_event["evA"], "moneyline", lock=ctx.lock, start=ctx.start, sport="mlb")
        f = feat.build(ctx, board, "moneyline", "home", written=LOCKED, open_market=opened)
        self.assertIsNotNone(f["open_fair"])
        self.assertAlmostEqual(f["fair_move_pts"], 100 * (f["consensus_fair"] - f["open_fair"]), places=2)
        self.assertEqual(feat.build(ctx, board, "moneyline", "home", written=LOCKED)["fair_move_pts"], None)

    def test_rest_days_where_we_have_results_and_none_where_we_do_not(self):
        _, ctx, board = ctx_board()
        f = feat.build(ctx, board, "moneyline", "home", written=LOCKED)
        # basic_stores: BOS played on 2026-09-12 at the latest; the days after are covered by no result row
        self.assertIsNone(f["rest_days_home"])
        games = [mlb_game(900 + i, f"2026-09-{10 + i:02d}", "TB", "BOS", 1, 0) for i in range(10)]
        stores = basic_stores(mlb_games=games, covered={f"2026-09-{d:02d}" for d in range(10, 21)})
        _, ctx2, board2 = ctx_board(stores)
        f2 = feat.build(ctx2, board2, "moneyline", "home", written=LOCKED)
        self.assertEqual(f2["rest_days_home"], 0)           # last game 09-19, game on 09-20 (ET): played yesterday = 0
        gap = [mlb_game(900 + i, f"2026-09-{10 + i:02d}", "TB", "BOS", 1, 0) for i in range(6)]      # last game 09-15
        covered = {f"2026-09-{d:02d}" for d in range(10, 20)}
        _, ctx_g, board_g = ctx_board(basic_stores(mlb_games=gap, covered=covered))
        self.assertEqual(feat.build(ctx_g, board_g, "moneyline", "home", written=LOCKED)["rest_days_home"], 4)
        _, ctx_u, board_u = ctx_board(basic_stores(mlb_games=gap, covered={"2026-09-10", "2026-09-15"}))
        self.assertIsNone(feat.build(ctx_u, board_u, "moneyline", "home", written=LOCKED)["rest_days_home"])   # days between not stored
        nba = base.Stores(sports=("mlb", "nfl", "nba"))
        for r in game_rows("evN", START, sport="nba", away="Boston Celtics", home="New York Knicks"):
            nba.add_row(r)
        nba.finalize()
        _, ctx3, board3 = ctx_board(nba, "evN")
        f3 = feat.build(ctx3, board3, "moneyline", "home", written=LOCKED)
        self.assertEqual((f3["rest_days_home"], f3["rest_days_away"], f3["rest_edge"]), (None, None, None))

    def test_features_come_only_from_data_observed_before_placement(self):
        """Add quotes observed after the lock (and one after the start), a different capture, and a finished result for this very
        game: the features must not move by a digit."""
        stores = basic_stores()
        _, ctx, board = ctx_board(stores)
        quotes = stores.quotes_by_event["evA"]
        opened = feat.open_market_board(quotes, "moneyline", lock=ctx.lock, start=ctx.start, sport="mlb")
        before = {(m, s): feat.build(ctx, board, m, s, written=LOCKED, open_market=feat.open_market_board(
            quotes, m, lock=ctx.lock, start=ctx.start, sport="mlb")) for m in base.MARKETS for s in base.SIDES[m]}
        late = game_rows("evA", START, observed=ctx.lock + timedelta(minutes=20), home_ml=-400, away_ml=330,
                         spread=(-3.5, -300, 250), total=(11.5, -300, 250))
        later = game_rows("evA", START, observed=START + timedelta(minutes=5), home_ml=-900, away_ml=600)
        for r in late + later:
            stores.add_row(r)
        stores.mlb_games.append(mlb_game(900001, "2026-09-20", "NYY", "BOS", 9, 1))      # this game's own result
        stores.finalize()
        ctx2 = base.build_context(stores, "evA")
        board2 = base.lock_board(stores, ctx2)
        after = {(m, s): feat.build(ctx2, board2, m, s, written=LOCKED, open_market=feat.open_market_board(
            stores.quotes_by_event["evA"], m, lock=ctx2.lock, start=ctx2.start, sport="mlb")) for m in base.MARKETS for s in base.SIDES[m]}
        self.assertEqual(before, after)
        self.assertIsNotNone(opened)

    def test_the_open_never_reads_a_capture_inside_the_hour_before_the_lock(self):
        stores = base.Stores()
        _, ctx, _b = ctx_board()
        for r in game_rows("evA", START, observed=ctx.lock - timedelta(minutes=30)):
            stores.add_row(r)
        stores.finalize()
        self.assertIsNone(feat.open_market_board(stores.quotes_by_event["evA"], "moneyline", lock=ctx.lock, start=ctx.start, sport="mlb"))


def multi_stores(n, *, price_rows=None):
    """n MLB games on 2026-09-20 (ET), staggered by 5 minutes, with an open and a lock capture each."""
    st = base.Stores()
    for i in range(n):
        start = START + timedelta(minutes=5 * i)
        for r in game_rows(f"ev{i:02d}", start, observed=start - timedelta(hours=10), home_ml=-120, away_ml=100):
            st.add_row(r)
        for r in game_rows(f"ev{i:02d}", start, observed=start - timedelta(hours=2), **(price_rows or {})):
            st.add_row(r)
    st.finalize()
    return st


class DrawTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.dir = Path(self._t.name)

    def bets(self, path):
        return [r for r in HashChainLedger(path).read() if r.get("kind") == pack_run.KIND_BET]

    def run_hound(self, h, stores, path, now=None, dates=("2026-09-20",)):
        return pack_run.run(stores, list(dates), replay=False, now=now or START - timedelta(minutes=10), path=path, hounds=[h],
                            out=lambda *a, **k: None)

    def test_it_draws_one_side_per_game_inside_the_band_and_logs_its_features(self):
        stores, ctx, board = ctx_board()
        sels = hound().bind(stores).pick(board, ctx)
        self.assertEqual(len(sels), 1)
        s = sels[0]
        self.assertEqual(s.stake, ai_defs.entry_for("learner")["stake_units"])
        f = s.row_extra["learner_features"]
        self.assertEqual((f["market"], f["side"]), (s.market, s.side))
        self.assertEqual((s.row_extra["learner_mode"], s.row_extra["rules_version"], s.row_extra["forward_only"]), ("explore", 0, True))
        self.assertIn("No rule yet", s.reason)

    def test_the_same_game_always_draws_the_same_bet(self):
        stores, ctx, board = ctx_board()
        a = hound().bind(stores).pick(board, ctx)[0]
        b = hound().bind(stores).pick(board, ctx)[0]
        self.assertEqual((a.market, a.side), (b.market, b.side))

    def test_minus_200_or_worse_is_never_drawn_even_when_it_is_the_only_side_in_a_market(self):
        stores = multi_stores(1, price_rows={"home_ml": -260, "away_ml": 215, "spread": None, "total": None})
        ctx = base.build_context(stores, "ev00")
        board = base.lock_board(stores, ctx)
        for _ in range(3):
            sels = hound().bind(stores).pick(board, ctx)
            self.assertEqual([(s.market, s.side) for s in sels], [("moneyline", "away")])
        stores2 = multi_stores(1, price_rows={"home_ml": -260, "away_ml": -240, "spread": None, "total": None})
        ctx2 = base.build_context(stores2, "ev00")
        self.assertEqual(hound().bind(stores2).pick(base.lock_board(stores2, ctx2), ctx2), [])

    def test_runner_enforces_the_cap_from_config_one_per_game_and_is_idempotent(self):
        stores = multi_stores(6)
        path = str(self.dir / "ledger.jsonl")
        h = hound(max_per_day=4)
        self.assertEqual(h.max_per_day, 4)
        counts = self.run_hound(h.bind(stores), stores, path)
        self.assertEqual(counts["written"], 4)
        rows = self.bets(path)
        self.assertEqual(len({r["event_id"] for r in rows}), 4)
        self.assertTrue(all(r["hound_id"] == "learner" and r["price_average"] > -200 for r in rows))
        self.assertTrue(all(r["learner_features"]["hours_to_start"] > 0 for r in rows))
        self.assertEqual(self.run_hound(h.bind(stores), stores, path)["written"], 0)
        self.assertEqual(len(self.bets(path)), 4)

    def test_the_shipped_cap_is_fifty(self):
        self.assertEqual(hound().max_per_day, 50)

    def test_its_bets_settle_like_every_other_hounds(self):
        stores = multi_stores(2)
        stores.mlb_games = [mlb_game(1, "2026-09-20", "NYY", "BOS", 3, 2)]
        stores.mlb_covered = {"2026-09-20"}
        path = str(self.dir / "ledger.jsonl")
        self.run_hound(hound().bind(stores), stores, path)
        out = pack_settle.settle(stores, now=START + timedelta(days=1), path=path)
        self.assertGreaterEqual(out["graded"] + out["pending"], 1)

    def test_a_replay_of_it_is_refused(self):
        stores = multi_stores(1)
        with self.assertRaises(ai_defs.ForwardOnlyError):
            pack_run.run(stores, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=str(self.dir / "l.jsonl"),
                         hounds=[hound().bind(stores)], out=lambda *a, **k: None)


class RunnerWiringTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.dir = Path(self._t.name)
        for target in ("urllib.request.urlopen", "socket.create_connection"):
            p = mock.patch(target, side_effect=AssertionError("a test reached for the network"))
            p.start()
            self.addCleanup(p.stop)

    def router(self):
        return R.Router(R.load_config(), env={}, adapters={}, usage=R.UsageStore(self.dir / "u.jsonl", clock=Clock("2026-09-20T22:40:00")))

    def run_pass(self, env):
        with mock.patch.dict(os.environ, env):
            return ai_runner.run_pass(now=LOCKED, router=self.router(), stores=basic_stores(), ledger=str(self.dir / "ai.jsonl"),
                                      decisions=str(self.dir / "d.jsonl"), refresh_stats=lambda: None)

    def test_a_pass_with_no_model_key_still_runs_the_learner_and_asks_no_model(self):
        report = self.run_pass({"GEMATRIA_HOUND": "off"})
        self.assertTrue(report.get("learner"))
        self.assertEqual(report["run"]["written"], 1)
        row = [r for r in HashChainLedger(str(self.dir / "ai.jsonl")).read() if r["kind"] == pack_run.KIND_BET][0]
        self.assertEqual(row["hound_id"], "learner")
        self.assertNotIn("provider", row)

    def test_the_kill_switch_keeps_it_out(self):
        report = self.run_pass({"GEMATRIA_HOUND": "off", "LEARNER_HOUND": "off", "PACK_CONSENSUS_HOUND": "off"})
        self.assertFalse(report.get("learner"))
        self.assertFalse(report.get("run"))

    def test_the_loop_starts_for_an_explicit_learner_on(self):
        self.assertTrue(ai_runner.loop_enabled({"LEARNER_HOUND": "on"}))
        self.assertFalse(ai_runner.loop_enabled({}))


# ---------------------------------------------------------------------------
# phase 2
# ---------------------------------------------------------------------------

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)          # cutoff 2026-10-12, forward week 10-12 .. 10-19


def lesson_rows(*, rng, days_back_start=22, days_forward=7, per_day=18, planted=True, win_scale=0.9, hound_id="learner"):
    """Settled Learner bets from 22 days before the cutoff through the forward week. Every bet wins with probability
    ``win_scale`` x its break-even, so noise loses the vig; with ``planted`` a +150 NHL moneyline segment wins 60%."""
    rows = []
    cutoff = learn.cutoff_for(NOW)
    sports = ("nhl", "nba")
    n = 0
    for d in range(-days_back_start, days_forward):
        day = cutoff + timedelta(days=d)
        for i in range(per_day):
            n += 1
            if planted and i < 3:
                sport, market, role, price, band, p = "nhl", "moneyline", "underdog", 150, "+100 to +180", 0.6
            else:
                sport, market = rng.choice(sports), rng.choice(("moneyline", "spread", "total"))
                price = rng.choice((-130, -105, 250))
                role = None if market == "total" else ("favorite" if price < 0 else "underdog")
                band = feat.band_of(price)
                be = 1 / (1 + 100 / abs(price)) if price < 0 else 100 / (price + 100)
                p = be * win_scale
            side = "over" if market == "total" else rng.choice(("home", "away"))
            win = rng.random() < p
            start = day + timedelta(hours=18, minutes=i)
            f = {"sport": sport, "market": market, "side": side, "role": role, "venue": None if market == "total" else side,
                 "price": price, "band": band, "books": rng.choice((4, 5, 6)), "best_vs_avg_pts": 1.0, "hours_to_start": 1.0,
                 "fair_move_pts": rng.choice((None, 0.5, -0.5)), "line_move": None, "rest_edge": None,
                 "start_hour_et": 19, "fair_minus_break_even": -2.0, "day_of_week": start.strftime("%a").lower(),
                 "consensus_fair": 0.5}
            eid, sel = f"e{n}", f"s{n}"
            rows.append({"kind": pack_run.KIND_BET, "hound_id": hound_id, "event_id": eid, "market": market, "selection": sel,
                         "price_average": price, "start_utc": base.iso(start), "stake": 0.25, "learner_features": f})
            dec = price / 100 + 1 if price > 0 else 1 + 100 / abs(price)
            rows.append({"kind": pack_run.KIND_GRADED, "hound_id": hound_id, "event_id": eid, "market": market, "selection": sel,
                         "result": "WIN" if win else "LOSS", "stake": 0.25,
                         "units_average_price": round(0.25 * (dec - 1), 4) if win else -0.25,
                         "graded_utc": base.iso(start + timedelta(hours=4))})
    return rows


class LearnTests(unittest.TestCase):
    def test_under_two_hundred_settled_bets_it_says_so_and_proposes_nothing(self):
        rows = lesson_rows(rng=random.Random(1), days_back_start=3, days_forward=0, per_day=10)
        self.assertLess(len(learn.settled_bets(rows)), 200)
        card = learn.propose(rows, now=NOW)
        self.assertTrue(card["nothing"])
        self.assertTrue(card["message"].startswith("Not enough settled bets to learn yet."))
        self.assertEqual((card["segments"], card["changes"], card["proposal_id"]), ([], [], None))
        self.assertTrue(card["paper_only"])

    def test_the_floor_cannot_be_lowered_from_config(self):
        rows = lesson_rows(rng=random.Random(1), days_back_start=3, days_forward=0, per_day=10)
        self.assertTrue(learn.propose(rows, now=NOW, min_settled=5)["nothing"])

    def test_a_split_too_thin_either_side_of_the_cutoff_proposes_nothing(self):
        rows = lesson_rows(rng=random.Random(1), days_back_start=1, days_forward=7, per_day=40)
        card = learn.propose(rows, now=NOW)
        self.assertTrue(card["nothing"])
        self.assertIn("thin", card["message"])

    def test_a_segment_that_held_on_the_forward_week_is_proposed_with_its_numbers_and_honest_words(self):
        rows = lesson_rows(rng=random.Random(7))
        card = learn.propose(rows, now=NOW)
        self.assertFalse(card["nothing"], card["message"])
        top = card["changes"][0]
        self.assertEqual(card["segments"][0], ("nhl", "moneyline", "underdog", "+100 to +180"))
        self.assertTrue(top["text"].startswith("Narrow toward NHL moneyline plus-money sides, +100 to +180"))
        self.assertGreater(top["train"]["roi"], 0)
        self.assertGreater(top["forward"]["roi"], 0)
        self.assertGreaterEqual(top["train"]["n"], learn.MIN_SEGMENT_TRAIN)
        self.assertGreaterEqual(top["forward"]["n"], learn.MIN_SEGMENT_FORWARD)
        self.assertGreaterEqual(card["segments_tested"], 5)
        self.assertIn("luck", card["honesty"])
        self.assertIn("beats_market_price", card["model"])
        for text in [card["message"], card["honesty"]] + [c["text"] + " " + c["why"] for c in card["changes"]]:
            self.assertIsNone(DOG.search(text), text)
            self.assertNotRegex(text.lower(), r"guarantee|will keep|sure thing")

    def test_pure_noise_that_loses_the_vig_proposes_nothing(self):
        card = learn.propose(lesson_rows(rng=random.Random(3), planted=False), now=NOW)
        self.assertTrue(card["nothing"])
        self.assertIn("nothing is proposed", card["message"].lower())

    def test_same_bets_same_card(self):
        rows = lesson_rows(rng=random.Random(7))
        a, b = learn.propose(rows, now=NOW), learn.propose(list(reversed(rows)), now=NOW)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_training_uses_only_bets_started_and_graded_before_the_cutoff(self):
        rows = lesson_rows(rng=random.Random(7))
        card = learn.propose(rows, now=NOW)
        cutoff = learn.cutoff_for(NOW)
        expect = [s for s in learn.settled_bets(rows) if s["start"] < cutoff and s["graded"] < cutoff]
        self.assertEqual(card["train_n"], len(expect))
        # a bet that started before the cutoff but settled after it is NOT training data
        straddler = next(r for r in rows if r["kind"] == pack_run.KIND_GRADED and base.parse_utc(r["graded_utc"]) < cutoff
                         and base.parse_utc(r["graded_utc"]) > cutoff - timedelta(hours=6))
        moved = [dict(r, graded_utc=base.iso(cutoff + timedelta(hours=1))) if r is straddler else r for r in rows]
        self.assertEqual(learn.propose(moved, now=NOW)["train_n"], card["train_n"] - 1)

    def test_the_forward_week_never_reaches_the_fit(self):
        """Flip every forward-week outcome: the weights (so the model's training log-loss inputs) are unchanged, only the
        forward verdicts move."""
        rows = lesson_rows(rng=random.Random(7))
        cutoff = learn.cutoff_for(NOW)
        graded_at = {r["event_id"]: r for r in rows if r["kind"] == pack_run.KIND_GRADED}
        bets = learn.settled_bets(rows)
        train = [b for b in bets if b["start"] < cutoff and b["graded"] < cutoff and b["result"] != "PUSH"]
        enc = learn.Encoder(train)
        w1 = learn.fit_logistic([enc.vector(b["features"]) for b in train], [1 if b["result"] == "WIN" else 0 for b in train])
        flipped = [dict(r, result="LOSS" if r["result"] == "WIN" else "WIN") if r["kind"] == pack_run.KIND_GRADED
                   and base.parse_utc(r["graded_utc"]) >= cutoff else r for r in rows]
        bets2 = learn.settled_bets(flipped)
        train2 = [b for b in bets2 if b["start"] < cutoff and b["graded"] < cutoff and b["result"] != "PUSH"]
        w2 = learn.fit_logistic([enc.vector(b["features"]) for b in train2], [1 if b["result"] == "WIN" else 0 for b in train2])
        self.assertEqual(w1, w2)
        self.assertTrue(graded_at)

    def test_another_hounds_bets_are_not_its_lessons(self):
        rows = lesson_rows(rng=random.Random(7), hound_id="gematria")
        self.assertEqual(learn.settled_bets(rows), [])

    def test_a_bet_with_no_frozen_features_is_not_a_lesson(self):
        rows = lesson_rows(rng=random.Random(7), days_back_start=2, days_forward=1, per_day=4)
        for r in rows:
            r.pop("learner_features", None)
        self.assertEqual(learn.settled_bets(rows), [])

    def test_the_logistic_fit_separates_a_clear_signal(self):
        rng = random.Random(0)
        X = [[1.0, x] for x in (rng.uniform(-2, 2) for _ in range(300))]
        y = [1 if x[1] + rng.gauss(0, 0.3) > 0 else 0 for x in X]
        w = learn.fit_logistic(X, y)
        self.assertGreater(w[1], 1.0)
        self.assertGreater(learn.predict(w, [1.0, 1.5]), 0.8)
        self.assertLess(learn.predict(w, [1.0, -1.5]), 0.2)


class ReviewBeforeApplyTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.path = str(Path(self._t.name) / lstate.EVENTS_NAME)
        self.card = learn.propose(lesson_rows(rng=random.Random(7)), now=NOW)
        self.assertFalse(self.card["nothing"])

    def test_proposing_applies_nothing(self):
        lstate.record_proposal(self.path, self.card, now=NOW)
        st = lstate.read(self.path)
        self.assertEqual((st["version"], st["focus"]), (0, []))
        self.assertEqual(st["pending"]["proposal_id"], self.card["proposal_id"])
        self.assertEqual(hound_with_events(self.path).focus, set())

    def test_an_empty_card_cannot_be_recorded(self):
        empty = learn.propose([], now=NOW)
        with self.assertRaises(lstate.StateError):
            lstate.record_proposal(self.path, empty)

    def test_apply_needs_the_cards_own_basis_and_then_the_hound_focuses(self):
        lstate.record_proposal(self.path, self.card, now=NOW)
        with self.assertRaises(lstate.StateError) as e:
            lstate.apply(self.path, self.card["proposal_id"], "0" * 16, actor="owner")
        self.assertEqual(e.exception.code, "basis_mismatch")
        lstate.apply(self.path, self.card["proposal_id"], self.card["basis"], actor="owner:1", now=NOW)
        st = lstate.read(self.path)
        self.assertEqual((st["version"], st["pending"]), (1, None))
        h = hound_with_events(self.path)
        self.assertEqual((h.rules_version, h.focus), (1, {tuple(s) for s in self.card["segments"]}))
        with self.assertRaises(lstate.StateError) as e2:
            lstate.apply(self.path, self.card["proposal_id"], self.card["basis"], actor="owner")
        self.assertEqual(e2.exception.code, "proposal_stale")
        self.assertTrue(HashChainLedger(self.path).verify().ok)

    def test_a_veto_closes_it_and_a_card_for_older_rules_is_stale(self):
        lstate.record_proposal(self.path, self.card, now=NOW)
        lstate.veto(self.path, self.card["proposal_id"], actor="owner")
        self.assertIsNone(lstate.read(self.path)["pending"])
        with self.assertRaises(lstate.StateError):
            lstate.apply(self.path, self.card["proposal_id"], self.card["basis"], actor="owner")
        old = dict(self.card, proposal_id="lp-old", rules_version=0, basis="b")
        lstate.record_proposal(self.path, old, now=NOW)
        lstate.apply(self.path, "lp-old", "b", actor="owner")
        newer = dict(self.card, proposal_id="lp-older", rules_version=0, basis="c")
        lstate.record_proposal(self.path, newer, now=NOW)
        self.assertIsNone(lstate.read(self.path)["pending"])           # drawn against rules v0, now v1

    def test_the_learn_step_has_no_path_to_apply(self):
        """propose() and the CLI's learn write at most a proposal; nothing in learn.py calls state.apply except the explicit command."""
        src = (ROOT / "src" / "hounds" / "learner" / "learn.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("lstate.apply("), 1)
        self.assertNotIn("apply(", src.split("def main")[0].replace("def propose", "").replace("lstate.apply(", ""))

    def test_a_focused_hound_draws_from_the_focus_and_passes_when_the_game_has_none(self):
        stores, ctx, board = ctx_board()
        h = hound(explore_share=0.0).bind(stores)
        h.focus, h.rules_version = {("mlb", "total", "over", "-149 to -110")}, 1
        sel = h.pick(board, ctx)
        self.assertEqual([(s.market, s.side) for s in sel], [("total", "over")])
        self.assertEqual((sel[0].row_extra["learner_mode"], sel[0].row_extra["rules_version"]), ("focus", 1))
        h.focus = {("nhl", "moneyline", "underdog", "+100 to +180")}
        self.assertEqual(h.pick(board, ctx), [])
        h.explore_share = 1.0
        self.assertEqual(len(h.pick(board, ctx)), 1)                     # the exploration share still bets anywhere


def hound_with_events(path):
    return learner_hound.LearnerHound(entry(), now_fn=lambda: LOCKED, events=path)


class CliTests(unittest.TestCase):
    def test_learn_prints_the_card_and_write_records_it_but_apply_is_separate(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = str(Path(d) / "ai.jsonl")
            with open(ledger, "w", encoding="utf-8") as fh:           # read() does not re-hash; appending 800 rows one by one is slow
                for r in lesson_rows(rng=random.Random(7)):
                    fh.write(json.dumps(r) + "\n")
            out = []
            with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(map(str, a)))):
                self.assertEqual(learn.main(["learn", "--ledger", ledger, "--now", "2026-10-20T12:00:00Z", "--write"]), 0)
            card = json.loads(out[0])
            self.assertFalse(card["nothing"])
            self.assertEqual(lstate.read(lstate.events_path(ledger))["version"], 0)
            self.assertIsNotNone(lstate.read(lstate.events_path(ledger))["pending"])
            out.clear()
            with mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(map(str, a)))):
                self.assertEqual(learn.main(["apply", card["proposal_id"], "--ledger", ledger, "--basis", "bad"]), 2)
                self.assertEqual(learn.main(["apply", card["proposal_id"], "--ledger", ledger, "--basis", card["basis"]]), 0)
            self.assertEqual(lstate.read(lstate.events_path(ledger))["version"], 1)

    def test_the_package_needs_no_web_framework(self):
        for name in ("__init__", "features", "state", "learn"):
            src = (ROOT / "src" / "hounds" / "learner" / f"{name}.py").read_text(encoding="utf-8")
            self.assertNotRegex(src, r"^\s*(import|from) (fastapi|numpy|sklearn|pandas)", )
        src = (ROOT / "src" / "hounds" / "pack" / "learner_hound.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(import|from) (fastapi|numpy|sklearn|pandas)")


if __name__ == "__main__":
    unittest.main()
