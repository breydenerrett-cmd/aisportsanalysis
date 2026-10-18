"""GET /hounds/digest: the daily Discord post, facts from code, voice from a betting server.

The story: a Zapier job let an AI write the race summary from the JSON and it said 21 hounds when the board
had 35. The post is now built deterministically (src/hounds/digest.py); these tests pin the count, the
W-L records and units (from fixture data, by hand), the closing-line verdict line, the responsible-gambling
line, the phrases the post may never use, the 900-character limit, the saved-copy path, and that the module
loads where FastAPI is not installed.

Route tests point ``HOUNDS_SNAPSHOT_PATH`` at a temp file (the lesson of tests/test_hounds_stats.py: an
un-injected store makes a test pass by machine).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import digest as D
from src.hounds import stats
from src.hounds.ledgers import Sources
from tests import _hounds_fixtures as F

if HAS_FASTAPI:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.hounds import router

ROOT = Path(__file__).resolve().parent.parent
BEAT, EARLY, VIG = "BEATING THE CLOSE", "TOO EARLY", "PAYING THE VIG"
CLOSING = "Paper bets only, not advice. 21+. Gamble responsibly: 1-800-GAMBLER"
LINK = ("https://linehound.app/web/hounds.html?utm_source=discord&utm_medium=digest"
        "&utm_campaign=hounds_daily")
FORBIDDEN = re.compile(r"edge|guarantee|\block(s|ed)?\b|can'?t lose|sure thing|profitable|"
                       r"tell you to bet|you should bet|money|\$|#", re.I)
EMOJIS = ("🐶", "🔥", "🥶", "🪙", "💀", "🧠")


def hound(hid, wins=0, losses=0, units=None, label=EARLY, category="stats", first="2026-10-01T18:00:00Z",
          name=None, **extra):
    record = {"bets": wins + losses, "wins": wins, "losses": losses, "units_recorded_price": units or 0.0,
              "units_average_price": units}
    return {"id": hid, "name": name or hid.replace("_", " ").title(), "category": category, "kind": "house",
            "verdict": {"label": label}, "record": record, "first_bet_utc": first, **extra}


def board(hounds, as_of="2026-10-18", **extra):
    return {"as_of": as_of, "hounds": hounds, "paper_only": True, **extra}


def graveyard(*rows):
    return {"hounds": [{"name": n, "retired": {"date": d, "cause": c}} for n, d, c in rows]}


def assert_clean(test, post):
    test.assertLessEqual(len(post), 900)
    test.assertIsNone(FORBIDDEN.search(post), post)
    test.assertEqual(post.splitlines()[-2:], [CLOSING, LINK])
    stripped = post
    for e in EMOJIS:
        stripped = stripped.replace(e, "")
    test.assertTrue(stripped.isascii(), stripped)           # no emoji beyond the fixed few
    test.assertLessEqual(sum(post.count(e) for e in EMOJIS), 6)


class Counts(unittest.TestCase):
    def test_the_count_is_len_hounds_including_baselines_and_unstarted(self):
        hs = [hound(f"h{i}") for i in range(32)] + [hound("beagle", category="baseline")] * 3
        out = D.digest(board(hs))
        self.assertEqual(out["hounds_total"], 35)
        self.assertIn("35 dogs in the race (paper bets, MLB and NFL).", out["post"].splitlines())

    def test_the_shape(self):
        out = D.digest(board([hound("a")]))
        self.assertEqual(set(out), {"post", "skip", "as_of", "hounds_total", "paper_only"})
        self.assertIs(out["skip"], False)
        self.assertIs(out["paper_only"], True)
        self.assertEqual(out["as_of"], "2026-10-18")

    def test_header_shows_the_boards_own_date(self):
        hs = [hound("a", first="2026-10-10T12:00:00Z"), hound("b", first="2026-10-05T01:00:00Z"),
              hound("c", first=None)]
        self.assertEqual(D.digest(board(hs))["post"].splitlines()[0], "🐶 LineHound Kennel | Sun Oct 18")
        # a stale copy's as_of is the BUILD time; the date comes from the data's own day
        stale = board(hs, as_of="2026-10-18T05:07:09Z", data_as_of="2026-10-17", stale=True)
        self.assertEqual(D.digest(stale)["post"].splitlines()[0], "🐶 LineHound Kennel | Sat Oct 17")

    def test_a_board_without_a_date_drops_the_date_not_the_post(self):
        b = board([hound("a", first=None)])
        b.pop("data_as_of", None)
        b["as_of"] = ""
        self.assertEqual(D.build_post(b).splitlines()[0], "🐶 LineHound Kennel")

    def test_always_ends_with_the_gambling_line_and_link(self):
        for hs in ([hound("a")], [hound("a", 5, 1, 3.0, BEAT)]):
            assert_clean(self, D.digest(board(hs), graveyard(("Gone", "2026-10-01", "retired by the owner")))["post"])


class HottestAndColdest(unittest.TestCase):
    def test_season_records_when_no_window(self):
        hs = [hound("setter", 63, 46, 11.3787), hound("pointer", 59, 55, -5.7032),
              hound("whippet", 51, 32, 6.2724)]
        post = D.digest(board(hs))["post"]
        self.assertIn("🔥 Hottest dog: Setter 63-46 season, +11.4u", post)
        self.assertIn("🥶 Ice cold: Pointer 59-55 season, -5.7u. Check its pulse.", post)

    def test_units_fall_back_to_the_recorded_price_when_average_is_not_reported(self):
        h = hound("x", 5, 2, None)
        h["record"]["units_recorded_price"] = 2.25
        self.assertIn("🔥 Hottest dog: X 5-2 season, +2.2u", D.digest(board([h]))["post"])

    def test_week_window_is_used_when_given_and_labelled(self):
        hs = [hound("setter", 63, 46, 11.0), hound("pointer", 59, 55, -5.0)]
        window = {"setter": {"wins": 2, "losses": 4, "units": -1.26}, "pointer": {"wins": 5, "losses": 2, "units": 3.04}}
        post = D.digest(board(hs), window=window)["post"]
        self.assertIn("🔥 Hottest dog: Pointer 5-2 last 7 days, +3.0u", post)
        self.assertIn("🥶 Ice cold: Setter 2-4 last 7 days, -1.3u. Check its pulse.", post)
        self.assertNotIn("season", post)

    def test_too_few_settled_or_no_direction_means_no_line(self):
        hs = [hound("a", 2, 0, 1.9), hound("b", 1, 1, 0.0), hound("c", 4, 0, 0.0)]
        post = D.digest(board(hs))["post"]
        self.assertNotIn("Hottest", post)
        self.assertNotIn("Ice cold", post)

    def test_baselines_never_headline(self):
        hs = [hound("beagle", 200, 100, 80.0, category="baseline"), hound("a", 4, 2, 1.0)]
        post = D.digest(board(hs))["post"]
        self.assertIn("Hottest dog: A 4-2", post)
        self.assertNotIn("Beagle", post)

    def test_ties_are_decided_by_wins_then_name(self):
        hs = [hound("b", 5, 3, 2.0), hound("a", 5, 3, 2.0), hound("c", 6, 4, 2.0)]
        self.assertIn("Hottest dog: C 6-4", D.digest(board(hs))["post"])
        hs = [hound("b", 5, 3, 2.0), hound("a", 5, 3, 2.0)]
        self.assertIn("Hottest dog: A 5-3", D.digest(board(hs))["post"])

    def test_zero_units_prints_a_plain_sign(self):
        self.assertEqual(D.units_text(-0.04), "+0.0u")
        self.assertEqual(D.units_text(4.26), "+4.3u")
        self.assertEqual(D.units_text(-3.14), "-3.1u")


class WeekStatsFromTheBook(unittest.TestCase):
    """week_stats on hand-built rows: W-L from forward settled bets in the 7 days, units from the series."""

    def data(self, bets, series, basis="average_price"):
        return NS(bets=[NS(segment=s, result=r, date=d) for s, r, d in bets],
                  series=[NS(date=d, cum_units_average_price=a, cum_units_recorded_price=r) for d, a, r in series],
                  summary=NS(spark_basis=basis))

    def test_window_counts_only_the_last_seven_days_forward_wins_and_losses(self):
        bets = [("forward", "win", "2026-10-18"), ("forward", "loss", "2026-10-12"),
                ("forward", "win", "2026-10-11"),      # one day outside: window is 10-12 .. 10-18
                ("forward", "push", "2026-10-15"), ("replay", "win", "2026-10-15"),
                ("forward", "win", "2026-10-19")]      # after as_of
        series = [("2026-10-10", 0.0, 0.0), ("2026-10-11", 0.9, 1.0), ("2026-10-12", -0.1, 0.0),
                  ("2026-10-18", 0.8, 0.9)]
        out = D.week_stats({"h": self.data(bets, series)}, "2026-10-18")
        self.assertEqual(out["h"]["wins"], 1)
        self.assertEqual(out["h"]["losses"], 1)
        self.assertAlmostEqual(out["h"]["units"], 0.8 - 0.9)   # 10-18 cum minus the 10-11 cum

    def test_units_follow_the_recorded_basis_when_that_is_the_headline(self):
        bets = [("forward", "win", "2026-10-18")]
        series = [("2026-10-17", None, 0.0), ("2026-10-18", None, 0.91)]
        out = D.week_stats({"h": self.data(bets, series, "recorded_price")}, "2026-10-18")
        self.assertAlmostEqual(out["h"]["units"], 0.91)

    def test_a_hound_with_no_settled_bet_in_the_window_is_absent(self):
        out = D.week_stats({"h": self.data([("forward", "win", "2026-09-01")], [("2026-09-01", 1.0, 1.0)])},
                           "2026-10-18")
        self.assertEqual(out, {})

    def test_bad_as_of_gives_nothing(self):
        self.assertEqual(D.week_stats({"h": self.data([], [])}, None), {})


class CoinFlip(unittest.TestCase):
    def pair(self, collie, prof):
        return [hound(D.COIN_FLIP_ID, *collie, name="Coin-Flip Collie", category="random"),
                hound(D.PROFESSOR_ID, *prof, name="Professor Paws")]

    def test_ahead_behind_and_level(self):
        post = D.digest(board(self.pair((3, 2, 1.0), (2, 3, -1.5))))["post"]
        self.assertIn("🪙 Coin-Flip Collie is ahead of Professor Paws (+1.0u vs -1.5u, season).", post)
        post = D.digest(board(self.pair((2, 3, -2.0), (3, 2, 1.0))))["post"]
        self.assertIn("🪙 Coin-Flip Collie is behind Professor Paws (-2.0u vs +1.0u, season).", post)
        post = D.digest(board(self.pair((3, 2, 1.0), (4, 3, 1.0))))["post"]
        self.assertIn("is level with Professor Paws", post)

    def test_left_out_when_either_has_no_settled_bet_or_is_missing(self):
        self.assertNotIn("🪙", D.digest(board(self.pair((0, 0, None), (2, 3, -1.5))))["post"])
        self.assertNotIn("🪙", D.digest(board([self.pair((3, 2, 1.0), (1, 1, 0.0))[0]]))["post"])


class SharpOrLucky(unittest.TestCase):
    def test_nobody(self):
        self.assertIn("🧠 Nobody's beating the closing line yet. The ref says it's all luck so far.",
                      D.digest(board([hound("a", 4, 2, 1.0, VIG), hound("b")]))["post"])

    def test_exactly_one(self):
        post = D.digest(board([hound("a", label=BEAT), hound("b", label=VIG)]))["post"]
        self.assertIn("🧠 Sharp or lucky? A is the only one beating the closing line.", post)

    def test_several_and_many(self):
        three = [hound(c, label=BEAT) for c in "cab"]
        self.assertIn("🧠 Sharp or lucky? 3 dogs are beating the closing line: A, B, C.",
                      D.digest(board(three))["post"])
        five = [hound(c, label=BEAT) for c in "edcba"]
        self.assertIn("5 dogs are beating the closing line: A, B, C and 2 more.", D.digest(board(five))["post"])

    def test_a_baseline_beating_the_close_does_not_count(self):
        post = D.digest(board([hound("beagle", label=BEAT, category="baseline")]))["post"]
        self.assertIn("Nobody's beating", post)

    def test_the_line_is_always_present(self):
        for hs in ([hound("a")], [hound("a", label=BEAT)]):
            self.assertIn("🧠", D.digest(board(hs))["post"])


class Graveyard(unittest.TestCase):
    def test_the_most_recently_retired_hound_in_plain_words(self):
        gy = graveyard(("Old", "2026-09-01", "retired by the owner"),
                       ("Newest", "2026-10-10", "retired: down more than 25 units"),
                       ("Middle", "2026-09-20", "retired by the owner"))
        post = D.digest(board([hound("a")]), gy)["post"]
        self.assertIn("💀 Graveyard: Newest (down more than 25 units)", post)
        self.assertEqual(post.count("Graveyard:"), 1)

    def test_other_causes(self):
        for cause, plain in (("retired: closing price verdict PAYING THE VIG at 300+ bets",
                              "couldn't beat the closing line over 300+ bets"),
                             ("retired by the owner", "the owner pulled it"),
                             ("paused 2026-10-16: paid a premium over the market's fair number",
                              "paused 2026-10-16: paid a premium over the market's fair number")):
            post = D.digest(board([hound("a")]), graveyard(("Gone", "2026-10-02", cause)))["post"]
            self.assertIn(f"💀 Graveyard: Gone ({plain})", post)
            assert_clean(self, post)

    def test_omitted_without_a_graveyard(self):
        for gy in (None, {"hounds": []}):
            self.assertNotIn("Graveyard", D.digest(board([hound("a")]), gy)["post"])

    def test_a_cause_that_breaks_the_rules_is_replaced(self):
        post = D.digest(board([hound("a")]), graveyard(("Odd", "2026-10-02", "had an edge, a lock, $40")))["post"]
        self.assertIn("💀 Graveyard: Odd (retired from the race)", post)
        assert_clean(self, post)


class Limits(unittest.TestCase):
    def test_the_post_never_passes_900_characters_and_keeps_its_ends(self):
        long = "X" * 400
        hs = [hound(f"id{i}", 9, 1, 5.0 + i, BEAT, name=f"{long}{i}") for i in range(5)] + \
             [hound("z", 0, 9, -5.0, name="Z" * 400)]
        out = D.digest(board(hs), graveyard((long, "2026-10-01", "x" * 800)))
        assert_clean(self, out["post"])
        self.assertTrue(out["post"].startswith("🐶 LineHound Kennel"))
        self.assertIn("🧠", out["post"])

    def test_graveyard_is_the_first_line_dropped(self):
        hs = [hound("a", 9, 1, 5.0, BEAT, name="A" * 40), hound("b", 1, 9, -5.0, name="B" * 40)]
        gy = graveyard(("G" * 40, "2026-10-01", "retired by the owner"))
        full = D.build_post(board(hs), gy)
        without = D.build_post(board(hs))
        self.assertIn("Graveyard", full)
        with mock.patch.object(D, "MAX_POST_CHARS", len(without)):
            tight = D.build_post(board(hs), gy)
        self.assertEqual(tight, without)
        self.assertIn("🔥", tight)

    def test_a_normal_post_fits(self):
        hs = [hound("setter", 63, 46, 11.4, label=BEAT), hound("pointer", 59, 55, -5.7)]
        post = D.digest(board(hs), graveyard(("The Old Dog", "2026-10-16", "paused 2026-10-16: paid a premium")))["post"]
        self.assertLess(len(post), 900)


class BannedPhrases(unittest.TestCase):
    def test_hostile_names_are_left_out_not_printed(self):
        hs = [hound("a", 20, 1, 9.0, name="Edge Finder"), hound("b", 19, 1, 8.0, name="Sure Thing Sam"),
              hound("c", 18, 1, 7.0, name="Lock of the Day"), hound("d", 17, 1, 6.0, name="Money Line"),
              hound("e", 16, 1, 5.0, name="Cash $ Cow"), hound("f", 15, 1, 4.0, name="Hash #Tag"),
              hound("g", 3, 1, 1.0, name="Clean One")]
        out = D.digest(board(hs))
        assert_clean(self, out["post"])
        self.assertEqual(out["hounds_total"], 7)
        self.assertIn("Hottest dog: Hash Tag", out["post"])      # '#' is stripped, the name survives

    def test_emoji_in_a_name_is_removed(self):
        post = D.digest(board([hound("a", 5, 1, 2.0, name="Rocket 🚀 Dog")]))["post"]
        self.assertIn("Hottest dog: Rocket Dog 5-1", post)
        assert_clean(self, post)

    def test_a_full_looking_post_is_clean(self):
        hs = [hound("setter", 63, 46, 11.4, BEAT), hound("pointer", 59, 55, -5.7, VIG)]
        gy = graveyard(("Gone", "2026-10-01", "retired: down more than 25 units"))
        assert_clean(self, D.digest(board(hs), gy)["post"])

    def test_never_calls_anyone_profitable_or_gives_advice(self):
        post = D.digest(board([hound("a", 60, 10, 40.0, BEAT)]))["post"].lower()
        for phrase in ("profitable", "edge", "guaranteed", "lock", "can't lose", "sure thing", "you should", "bet on"):
            self.assertNotIn(phrase, post)


class NoData(unittest.TestCase):
    def test_skip_only_without_a_leaderboard(self):
        for payload in (None, {}, {"warming_up": True, "hounds": []}, {"hounds": []}):
            out = D.digest(payload)
            self.assertIs(out["skip"], True)
            self.assertEqual(out["post"], "")
            self.assertEqual(out["hounds_total"], 0)
            self.assertIs(out["paper_only"], True)

    def test_stale_copy_counts_as_data(self):
        self.assertIs(D.digest({**board([hound("a")]), "stale": True})["skip"], False)


class WithoutFastAPI(unittest.TestCase):
    def test_module_loads_and_builds_with_fastapi_hidden(self):
        code = (
            "import sys; sys.modules['fastapi'] = None; sys.modules['starlette'] = None\n"
            "from src.hounds import digest as D\n"
            "out = D.digest({'as_of': '2026-10-18', 'hounds': [{'id': 'a', 'name': 'A', 'category': 'stats', "
            "'verdict': {'label': 'TOO EARLY'}, 'record': {'bets': 2, 'wins': 2, 'losses': 0, "
            "'units_recorded_price': 1.0}}]})\n"
            "assert out['hounds_total'] == 1 and not out['skip'], out\n"
            "assert 'fastapi' not in [m for m, v in sys.modules.items() if v is not None]\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Route(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src = F.make_world(root / "world")
        self.path = root / "volume" / "hounds_public_cache.json"
        self._env = mock.patch.dict(os.environ, {stats.ENV_SNAPSHOT_PATH: str(self.path)})
        self._env.start()
        self._default = mock.patch.object(Sources, "default", staticmethod(lambda: self.src))
        self._default.start()
        stats.clear_cache()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        stats.clear_cache()
        self._default.stop()
        self._env.stop()
        self._tmp.cleanup()

    def go_cold(self):
        stats._CACHE["book"] = None
        stats._BG.update(error=None, failed_at=0.0, thread=None)

    def test_route_is_mounted_and_returns_the_shape_not_a_hound_id(self):
        book = stats.get_book(self.src)
        r = self.client.get("/hounds/digest")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(set(body), {"post", "skip", "as_of", "hounds_total", "paper_only"})
        self.assertIs(body["skip"], False)
        self.assertIs(body["paper_only"], True)
        self.assertEqual(body["hounds_total"], len(stats.leaderboard(book)))
        self.assertEqual(body["as_of"], book.as_of)
        self.assertIn(f"{len(stats.leaderboard(book))} dogs in the race (paper bets", body["post"])
        assert_clean(self, body["post"])
        self.assertIn("max-age", r.headers["cache-control"])

    def test_the_records_in_the_post_are_the_boards_own(self):
        """Every W-L the post prints, over 7 days, equals what the fixture's forward bets say."""
        book = stats.get_book(self.src)
        week = D.week_stats(book.hounds, book.as_of)
        for hid, w in week.items():
            data = book.hounds[hid]
            start = D._window_start(book.as_of[:10])
            rows = [b for b in data.bets if b.segment == "forward" and b.result in ("win", "loss")
                    and start <= b.date[:10] <= book.as_of[:10]]
            self.assertEqual((w["wins"], w["losses"]),
                             (sum(b.result == "win" for b in rows), sum(b.result == "loss" for b in rows)))
        season = {s.id: s for s in stats.leaderboard(book)}
        post = self.client.get("/hounds/digest").json()["post"]
        for line in post.splitlines():
            m = re.match(r"[🔥🥶] (?:Hottest dog|Ice cold): (.+?) (\d+)-(\d+) (last 7 days|season)", line)
            if not m:
                continue
            h = next(s for s in season.values() if s.name == m.group(1))
            if m.group(4) == "season":
                self.assertEqual((int(m.group(2)), int(m.group(3))), (h.record.wins, h.record.losses))
            else:
                self.assertEqual((int(m.group(2)), int(m.group(3))),
                                 (week[h.id]["wins"], week[h.id]["losses"]))

    def test_get_only(self):
        self.assertEqual(self.client.post("/hounds/digest", json={}).status_code, 405)

    def test_stale_copy_path_never_warms_up_and_uses_season_records(self):
        book = stats.get_book(self.src)
        stats.write_snapshot(book)
        self.go_cold()
        with mock.patch.object(stats, "refresh_async", return_value=True) as rebuild:
            r = self.client.get("/hounds/digest")
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("warming_up", body)
        self.assertIs(body["skip"], False)
        self.assertEqual(body["as_of"], book.built_utc)            # the saved copy's build time
        self.assertEqual(body["hounds_total"], len(stats.leaderboard(book)))
        self.assertNotIn("last 7 days", body["post"])               # no per-bet rows in the copy: say season
        self.assertEqual(r.headers["cache-control"], "no-store")
        assert_clean(self, body["post"])
        rebuild.assert_called_once()

    def test_no_data_and_no_copy_skips(self):
        with mock.patch.object(stats, "refresh_async", return_value=True):
            body = self.client.get("/hounds/digest").json()
        self.assertIs(body["skip"], True)
        self.assertEqual(body["post"], "")

    def test_an_old_copy_is_not_data(self):
        import json
        book = stats.get_book(self.src)
        stats.write_snapshot(book)
        self.go_cold()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["built_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 25 * 3600))
        self.path.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.object(stats, "refresh_async", return_value=True):
            self.assertIs(self.client.get("/hounds/digest").json()["skip"], True)

    def test_a_failed_first_build_with_no_copy_skips_instead_of_503(self):
        stats._BG.update(error="boom", failed_at=time.time(), thread=None)
        r = self.client.get("/hounds/digest")
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.json()["skip"], True)

    def test_mounted_in_the_real_app(self):
        from api.app import app
        stats.get_book(self.src)
        r = TestClient(app).get("/hounds/digest")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("post", r.json())


if __name__ == "__main__":
    unittest.main()
