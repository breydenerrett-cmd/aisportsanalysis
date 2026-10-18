"""House pack hounds: registry, determinism, worked examples, committed seeds, each rule fires."""

from __future__ import annotations

import hashlib
import importlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.hounds import pack as pack_mod
from src.hounds.pack import base
from src.hounds.pack import (coin_flip_collie, dartboard_dalmatian, elimination_basset, lunar_lab,
                             numerology_newfie)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
BOOKS = ("betmgm", "draftkings", "fanduel", "caesars", "betrivers")


def T(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def game_rows(eid, start, *, away="New York Yankees", home="Boston Red Sox", sport="mlb",
              observed=None, home_ml=-130, away_ml=110, books=BOOKS, spread=(-1.5, 140, -165),
              total=(8.5, -110, -110)):
    """Multibook rows for one capture instant: moneyline, spread and total for every book."""
    observed = observed or start - timedelta(hours=2)
    out = []
    for i, book in enumerate(books):
        common = {"observed_utc": iso(observed), "event_id": eid, "commence_time": iso(start).replace("+00:00", "Z"),
                  "home_team": home, "away_team": away, "book": book}
        if sport != "mlb":
            common["sport"] = sport
        out.append(dict(common, home_price=home_ml, away_price=away_ml))
        if spread:
            hl, hp, ap = spread
            out.append(dict(common, market="spreads", home_line=hl, away_line=-hl, home_price=hp, away_price=ap))
        if total:
            tl, op, up = total
            out.append(dict(common, market="totals", total=str(tl), over_price=op, under_price=up))
    return out


def mlb_game(pk, day, away, home, a, h, game_type="R"):
    return {"game_pk": str(pk), "date": day, "start_utc": f"{day}T23:05:00Z", "game_type": game_type,
            "away": away, "home": home, "away_score": a, "home_score": h, "source": "results"}


START = T("2026-09-20T23:05:00")


def basic_stores(extra_rows=(), mlb_games=None, bullpen=None, covered=None) -> base.Stores:
    st = base.Stores()
    for r in game_rows("evA", START, observed=START - timedelta(hours=10), home_ml=-120, away_ml=100):
        st.add_row(r)
    for r in game_rows("evA", START, observed=START - timedelta(hours=2)):
        st.add_row(r)
    for r in extra_rows:
        st.add_row(r)
    st.event_map = {"evA": {"game_pk": "900001", "event_id": "evA"}}
    if mlb_games is None:
        mlb_games = []
        for i in range(12):
            day = (datetime(2026, 9, 1) + timedelta(days=i)).date().isoformat()
            mlb_games.append(mlb_game(800000 + i, day, "NYY", "TOR", 6, 2))
            mlb_games.append(mlb_game(810000 + i, day, "TB", "BOS", 5, 3))
    st.mlb_games = list(mlb_games)
    st.mlb_covered = set(covered if covered is not None else {g["date"] for g in st.mlb_games})
    st.bullpen = list(bullpen or [])
    st.finalize()
    return st


def all_picks(stores, eid="evA"):
    ctx = base.build_context(stores, eid)
    board = base.lock_board(stores, ctx)
    out = {}
    for h in pack_mod.PACK:
        if h.applies_to(ctx.sport):
            out[h.id] = [(s.market, s.side, s.score, s.reason, s.stake) for s in h.pick(board, ctx)]
    return out


class RegistryTests(unittest.TestCase):
    def test_twenty_one_unique_hounds_with_valid_categories(self):
        ids = [h.id for h in pack_mod.PACK]
        self.assertEqual(len(ids), 21)
        self.assertEqual(len(set(ids)), 21)
        cats = {"stats", "history", "market", "math", "intangibles", "esoteric", "random", "mixed", "simple"}
        for h in pack_mod.PACK:
            self.assertIn(h.category, cats, h.id)
            self.assertTrue(h.name and h.tagline and h.RULE and h.sports and h.markets, h.id)
            self.assertIn(h.who_decided, ("rule", "model", "random"))
        self.assertEqual({h.category for h in pack_mod.PACK}, cats)

    def test_config_registry_matches_code_exactly(self):
        cfg = json.loads((ROOT / "config" / "house_pack.json").read_text(encoding="utf-8"))
        rows = {r["id"]: r for r in cfg["hounds"]}
        self.assertEqual(set(rows), set(pack_mod.BY_ID))
        for hid, h in pack_mod.BY_ID.items():
            r = rows[hid]
            self.assertEqual(r["rule_text"], h.RULE, hid)
            self.assertEqual(r["name"], h.name)
            self.assertEqual(r["category"], h.category)
            self.assertEqual(r["tagline"], h.tagline)
            self.assertEqual(tuple(r["sports"]), h.sports)
            self.assertEqual(tuple(r["markets"]), h.markets)
            mod = importlib.import_module(r["module"])
            self.assertIs(mod.HOUND, h)
            self.assertEqual(r["ledger"], "evidence/hounds_house_v1.jsonl")
            self.assertTrue((ROOT / "docs" / "hounds" / f"{hid}.md").exists(), hid)


class WorkedExampleTests(unittest.TestCase):
    def test_gematria_matches_prereg(self):
        g, dr = numerology_newfie.gematria, numerology_newfie.digital_root
        self.assertEqual((g("New York Yankees"), dr(191)), (191, 2))
        self.assertEqual((g("Boston Red Sox"), dr(170)), (170, 8))
        self.assertEqual((g("Kansas City Chiefs"), dr(172)), (172, 1))
        self.assertEqual((g("Athletics"), dr(97)), (97, 7))
        self.assertEqual(numerology_newfie.date_number("2026-09-08"), 9)

    def test_moon_phase_matches_prereg(self):
        self.assertAlmostEqual(lunar_lab.moon_age(T("2024-04-08T18:21:00")), 29.359, places=2)
        self.assertAlmostEqual(lunar_lab.moon_age(T("2024-04-23T23:49:00")), 15.056, places=2)
        self.assertEqual(lunar_lab.phase(T("2024-04-08T18:21:00")), "new")
        self.assertEqual(lunar_lab.phase(T("2024-04-23T23:49:00")), "full")
        self.assertEqual(lunar_lab.phase(T("2024-04-16T12:00:00")), "other")

    def test_random_seeds_are_committed(self):
        b = hashlib.sha256(b"coin_flip_collie|evA").digest()
        self.assertEqual(base.seed_bytes("coin_flip_collie", "evA"), b)
        st = basic_stores()
        ctx = base.build_context(st, "evA")
        board = base.lock_board(st, ctx)
        sel = coin_flip_collie.HOUND.pick(board, ctx)[0]
        self.assertEqual(sel.side, "home" if b[0] % 2 == 0 else "away")
        d = hashlib.sha256(b"dartboard_dalmatian|evA").digest()
        dsel = dartboard_dalmatian.HOUND.pick(board, ctx)[0]
        market = ("moneyline", "spread", "total")[d[0] % 3]
        self.assertEqual(dsel.market, market)
        self.assertEqual(dsel.side, base.SIDES[market][0] if d[1] % 2 == 0 else base.SIDES[market][1])


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_same_picks_for_every_hound(self):
        a = all_picks(basic_stores())
        b = all_picks(basic_stores())
        self.assertEqual(a, b)
        self.assertEqual(set(a), {h.id for h in pack_mod.PACK if h.applies_to("mlb")})


class RuleTests(unittest.TestCase):
    def test_board_prices(self):
        st = basic_stores()
        ctx = base.build_context(st, "evA")
        self.assertEqual(ctx.lock, START - timedelta(minutes=60))
        self.assertEqual(ctx.date, "2026-09-20")
        board = base.lock_board(st, ctx)
        home = board["markets"]["moneyline"]["sides"]["home"]
        self.assertEqual(home["price_average"], -130)
        self.assertEqual(home["book_count"], 5)
        self.assertEqual(home["book"], "betmgm")     # all tied: alphabetical
        self.assertEqual(board["markets"]["spread"]["line"], -1.5)

    def test_hot_streak_and_model_fire_on_a_hot_cold_matchup(self):
        picks = all_picks(basic_stores())
        self.assertEqual(picks["hot_streak_husky"][0][:2], ("moneyline", "away"))   # NYY 12-0, BOS 0-12
        self.assertEqual(picks["professor_paws"][0][:2], ("moneyline", "away"))

    def test_steam_and_contrarian(self):
        picks = all_picks(basic_stores())      # open home fair ~0.523, lock ~0.546: +2.3 points, below 3.0
        self.assertEqual(picks["steamy_setter"], [])
        st = base.Stores()
        for r in game_rows("evA", START, observed=START - timedelta(hours=10), home_ml=105, away_ml=-125):
            st.add_row(r)
        for r in game_rows("evA", START, observed=START - timedelta(hours=2)):
            st.add_row(r)
        st.finalize()
        ctx = base.build_context(st, "evA")
        board = base.lock_board(st, ctx)
        self.assertEqual(pack_mod.BY_ID["steamy_setter"].pick(board, ctx)[0].side, "home")
        self.assertEqual(pack_mod.BY_ID["contrary_corgi"].pick(board, ctx)[0].side, "away")

    def test_elimination_basset(self):
        games = [mlb_game(1, "2026-10-10", "NYY", "BOS", 5, 1, "D"), mlb_game(2, "2026-10-11", "NYY", "BOS", 4, 2, "D")]
        start = T("2026-10-13T23:05:00")
        st = base.Stores()
        for r in game_rows("evE", start, home="Boston Red Sox", away="New York Yankees"):
            st.add_row(r)
        st.mlb_games = games
        st.finalize()
        ctx = base.build_context(st, "evE")
        board = base.lock_board(st, ctx)
        sel = elimination_basset.HOUND.pick(board, ctx)
        self.assertEqual(len(sel), 1)
        self.assertEqual(sel[0].side, "home")
        st.mlb_games = games[:1]           # 1-0: no elimination yet
        ctx = base.build_context(st, "evE")
        self.assertEqual(elimination_basset.HOUND.pick(board, ctx), [])

    def test_numerology_ties_pass(self):
        st = base.Stores()
        # both names reduce to the same root -> equal distance -> pass
        for r in game_rows("evN", START, away="abc", home="cba"):
            st.add_row(r)
        st.finalize()
        ctx = base.build_context(st, "evN")
        board = base.lock_board(st, ctx)
        self.assertEqual(numerology_newfie.HOUND.pick(board, ctx), [])

    def test_kelly_stake_scales(self):
        from src.hounds.pack import kelly_kelpie

        self.assertEqual(kelly_kelpie.stake_for(0.52, 100), 1.0)
        self.assertEqual(kelly_kelpie.stake_for(0.48, 100), 0.0)


if __name__ == "__main__":
    unittest.main()
