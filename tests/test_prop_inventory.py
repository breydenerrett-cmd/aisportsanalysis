"""Tests for scripts/prop_inventory.py.

A small fixture world (prop stores, event map, box store, credit logs,
historical stores) is written to a temp directory and the inventory is built
from it, so every number below is a hand computation. Nothing here opens the
real stores.

Pinned behaviours:
  * books per line and two-sided hold match a hand computation;
  * only the newest shared instant of a contract is read;
  * a family with one-sided quotes only reports hold as UNKNOWN, never 0;
  * a row dated inside the sealed window 2026-01-01..2026-08-27 is skipped
    UNPARSED and counted, in the outcome store and in every other store;
  * the script is read-only on its inputs.
"""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts import prop_inventory as pi


def _write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for line in lines:
            fh.write((line if isinstance(line, str) else json.dumps(line, sort_keys=True)) + "\n")


def _tree_hashes(root):
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


E1, E2, E3 = "ev1", "ev2", "ev3"
OBS_OLD = "2026-09-12T20:00:00.000000Z"
OBS_NEW = "2026-09-12T22:30:00.000000Z"
COMMENCE = "2026-09-12T23:00:00Z"


def _pk(book, player, over, under, obs=OBS_NEW, event=E1, date="2026-09-12",
        point=5.5, commence=COMMENCE):
    return {"book": book, "player": player, "over_price": over,
            "under_price": under, "point": point, "market": "pitcher_strikeouts",
            "event_id": event, "game_date": date, "observed_utc": obs,
            "commence_time": commence, "slot": "T-30m", "credits_last": 1,
            "home_team": "H", "away_team": "A"}


def _bp(book, player, side, price, market="batter_hits", line="0.5", obs=OBS_NEW,
        event=E1, date="2026-09-12"):
    return {"book": book, "player": player, "side": side, "price": price,
            "line": line, "market": market, "event_id": event,
            "game_date": date, "observed_utc": obs, "commence_time": COMMENCE,
            "home_team": "H", "away_team": "A"}


def build_world(root):
    proc = Path(root) / "data" / "processed"
    hist = Path(root) / "data" / "historical"
    live = Path(root) / "data" / "live"

    # --- pitcher strikeouts: contract (E1, Ace One, 5.5) --------------------
    pp = [
        # an OLDER board with different books/prices: must be ignored
        _pk("bookA", "Ace One", -150, 130, obs=OBS_OLD),
        _pk("bookB", "Ace One", -150, 130, obs=OBS_OLD),
        # the NEWEST board: three two-sided books and one over-only book
        _pk("bookA", "Ace One", -110, -110),
        _pk("bookB", "Ace One", 100, -120),
        _pk("bookC", "Ace One", -105, -115),
        _pk("bookD", "Ace One", -130, None),
        # E2: a contract whose only box row is dated inside the sealed window
        _pk("bookA", "Sealed Sam", -110, -110, event=E2, date="2026-09-13",
            commence="2026-09-13T23:00:00Z", obs="2026-09-13T22:30:00.000000Z"),
        # marker row (no market key): one billed fetch
        {"event_id": E1, "game_date": "2026-09-12", "observed_utc": OBS_NEW,
         "poll": True, "credits_last": 1, "slot": "T-30m",
         "commence_time": COMMENCE, "books_priced": 4},
    ]
    _write_lines(proc / "prop_prices.jsonl", pp)

    # --- batter props: hits is Over-only everywhere; total bases two-sided ---
    bp = [
        _bp("bookA", "Bat One", "Over", -200),
        _bp("bookB", "Bat One", "Over", -210),
        _bp("bookA", "Bat One", "Over", 120, market="batter_total_bases", line="1.5"),
        _bp("bookA", "Bat One", "Under", -150, market="batter_total_bases", line="1.5"),
        _bp("bookB", "Bat One", "Over", 130, market="batter_total_bases", line="1.5"),
        _bp("bookB", "Bat One", "Under", -160, market="batter_total_bases", line="1.5"),
    ]
    _write_lines(proc / "batter_props.jsonl", bp)
    _write_lines(proc / "batter_props_raw.jsonl", [
        {"event_id": E1, "game_date": "2026-09-12", "observed_utc": OBS_NEW,
         "poll": True, "credits_last": 5, "family": "batter_props_floor",
         "capture_phase": "gate", "commence_time": COMMENCE}])

    # --- event map: E1 -> pk 100, E2 -> pk 200, plus a SEALED event ----------
    _write_lines(proc / "event_game_map.jsonl", [
        {"event_id": E1, "game_pk": 100, "resolved": True, "ambiguous": False,
         "commence_time": COMMENCE},
        {"event_id": E2, "game_pk": 200, "resolved": True, "ambiguous": False,
         "commence_time": "2026-09-13T23:00:00Z"},
        {"event_id": E3, "game_pk": 300, "resolved": True, "ambiguous": False,
         "commence_time": "2026-06-01T23:00:00Z"},
    ])

    # --- box store: pk 100 rows, and a row inside the sealed window ----------
    _write_lines(proc / "boxscores_2026.jsonl", [
        {"date": "2026-09-12", "game_pk": 100, "type": "pitcher",
         "player_name": "Ace One", "k": 7, "player_id": 1},
        {"date": "2026-09-12", "game_pk": 100, "type": "batter",
         "player_name": "Bat One", "h": 2, "total_bases": 3, "player_id": 2},
        # dated inside 2026-01-01..2026-08-27: must be skipped unparsed
        {"date": "2026-07-04", "game_pk": 200, "type": "pitcher",
         "player_name": "Sealed Sam", "k": 9, "player_id": 3},
        # a forward row on E2's date, so that date counts as ingested
        {"date": "2026-09-13", "game_pk": 200, "type": "pitcher",
         "player_name": "Other Guy", "k": 3, "player_id": 4},
    ])

    # --- credit logs ---------------------------------------------------------
    _write_lines(proc / "credit_log.jsonl", [
        {"caller": "x", "credits_remaining": 1000, "credits_used_last": 0,
         "utc": "2026-09-12T10:00:00.000000Z"},
        {"caller": "x", "credits_remaining": 900, "credits_used_last": 0,
         "utc": "2026-09-12T11:00:00.000000Z"},
        {"caller": "x", "credits_remaining": 850, "credits_used_last": 0,
         "utc": "2026-09-12T12:00:00.000000Z"},
        {"caller": "x", "credits_remaining": 840, "credits_used_last": 0,
         "utc": "2026-09-13T01:00:00.000000Z"},
    ])
    _write_lines(live / "credit_log_live.jsonl", [
        {"caller": "live", "credits_remaining": None, "credits_used_last": 1,
         "utc": "2026-09-12T20:00:00.000000Z"}])

    # --- historical stores ---------------------------------------------------
    _write_lines(hist / "pitcher_logs.jsonl", [
        {"person_id": 1, "date": "2025-06-01", "strikeouts": 4},
        # sealed-window row: deliberately NOT valid JSON, so a parse would blow up
        '{"person_id": 1, "date": "2026-05-01", "strikeouts": ',
        {"person_id": 1, "date": "2026-09-05", "strikeouts": 6},
    ])
    _write_lines(hist / "bullpen_log.jsonl", [{"date": "2026-09-01", "x": 1}])
    _write_lines(hist / "lineups.jsonl", [
        {"date": "2026-09-12", "observed_utc": "2026-09-12T18:00:00Z"}])
    (hist / "handedness.json").write_text(
        json.dumps({"1": {"bats": "R", "throws": "R"}}), encoding="utf-8")


class InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        build_world(cls.root)
        cls.before = _tree_hashes(cls.root)
        cls.paths = pi.Paths(cls.root)
        cls.inv = pi.build_inventory(cls.paths, since="2026-09-10")
        cls.fam = {f["family"]: f for f in cls.inv["families"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # -- books per line and hold, by hand ------------------------------------

    def test_books_per_line(self):
        rows, _ = pi.read_dated(self.paths.prop_prices, "game_date", "2026-09-10")
        cs = pi.build_contracts(pi._quotes_prop_prices(rows, "pitcher_strikeouts"))
        ace = [c for c in cs if c["player"] == "Ace One"][0]
        # newest board of (E1, Ace One, 5.5): A, B, C two-sided, D over only
        self.assertEqual(ace["books_any"], 4)
        self.assertEqual(sorted(ace["two_sided"]), ["bookA", "bookB", "bookC"])
        self.assertEqual(ace["one_sided"], ["bookD"])
        f = self.fam["pitcher strikeouts"]
        # medians over the two contracts: books [4, 1] and two-sided [3, 1]
        self.assertEqual(f["books_any_median"], 2.5)
        self.assertEqual(f["two_sided_books_median"], 2.0)
        self.assertEqual(f["book_quotes_two_sided"], 4)   # A,B,C on E1 + A on E2
        self.assertEqual(f["book_quotes_one_sided"], 1)   # D
        self.assertEqual(f["one_sided_by_book"], {"bookD": 1})

    def test_two_sided_hold_by_hand(self):
        f = self.fam["pitcher strikeouts"]
        p = lambda a: (abs(a) / (abs(a) + 100.0)) if a < 0 else 100.0 / (a + 100.0)
        # booksums of the pairs on the final board, E1: A -110/-110, B +100/-120,
        # C -105/-115; E2: A -110/-110
        sums = [p(-110) + p(-110), p(100) + p(-120), p(-105) + p(-115),
                p(-110) + p(-110)]
        margins = sorted((s - 1.0) * 100.0 for s in sums)
        holds = sorted((s - 1.0) / s * 100.0 for s in sums)
        med = lambda xs: (xs[1] + xs[2]) / 2.0     # four values
        self.assertEqual(f["hold_pairs"], 4)
        self.assertAlmostEqual(f["margin_median_pct"], round(med(margins), 2), places=2)
        self.assertAlmostEqual(f["hold_median_pct"], round(med(holds), 2), places=2)

    def test_total_bases_two_books_hold_by_hand(self):
        f = self.fam["batter total bases"]
        p = lambda a: (abs(a) / (abs(a) + 100.0)) if a < 0 else 100.0 / (a + 100.0)
        m1 = (p(120) + p(-150) - 1.0) * 100.0
        m2 = (p(130) + p(-160) - 1.0) * 100.0
        self.assertEqual(f["two_sided_books_median"], 2)
        self.assertEqual(f["hold_pairs"], 2)
        self.assertAlmostEqual(f["margin_median_pct"], round((m1 + m2) / 2.0, 2), places=2)

    def test_only_newest_shared_instant_is_read(self):
        # the older board (A,B at -150/+130) would add two quotes and a
        # different margin; none of it may appear
        rows, _ = pi.read_dated(self.paths.prop_prices, "game_date", "2026-09-10")
        cs = pi.build_contracts(pi._quotes_prop_prices(rows, "pitcher_strikeouts"))
        ace = [c for c in cs if c["player"] == "Ace One"][0]
        self.assertEqual(ace["observed"], OBS_NEW)
        self.assertEqual(ace["two_sided"]["bookA"], (-110, -110))   # not -150/+130
        f = self.fam["pitcher strikeouts"]
        self.assertEqual(f["contracts_off_final_board"], 0)

    # -- one-sided families are UNKNOWN, never zero --------------------------

    def test_one_sided_family_hold_is_unknown_not_zero(self):
        f = self.fam["batter hits"]
        self.assertTrue(f["captured"])
        self.assertEqual(f["eligible"], 0)
        self.assertEqual(f["hold_pairs"], 0)
        self.assertEqual(f["margin_median_pct"], pi.UNKNOWN)
        self.assertEqual(f["hold_median_pct"], pi.UNKNOWN)
        self.assertIn("hold_reason", f)
        self.assertEqual(f["book_quotes_one_sided"], 2)
        text = pi.render_markdown(self.inv)
        self.assertIn("UNKNOWN", text)

    def test_uncaptured_family_is_marked_not_captured(self):
        f = self.fam["pitcher outs"]
        self.assertFalse(f["captured"])
        self.assertNotIn("hold_median_pct", f)
        self.assertFalse(self.fam["QB passing yards"]["captured"])

    # -- the sealed window ---------------------------------------------------

    def test_sealed_box_row_skipped_and_counted(self):
        tally = self.inv["stores"]["boxscores_2026"]
        self.assertEqual(tally["sealed_skipped"], 1)
        self.assertEqual(tally["parsed"], 3)
        # E2's pitcher can only settle off the sealed row, so he must not settle
        f = self.fam["pitcher strikeouts"]
        self.assertEqual(f["eligible"], 2)
        self.assertEqual(f["settleable_eligible"], 1)          # Ace One only
        self.assertEqual(f["eligible_no_box_row"], 1)          # Sealed Sam

    def test_sealed_event_map_row_skipped(self):
        self.assertEqual(self.inv["stores"]["event_game_map"]["sealed_skipped"], 1)

    def test_sealed_line_is_never_parsed(self):
        # the sealed pitcher-log line is truncated JSON: a parse would count it
        # as unparseable; the gate must count it as sealed instead
        span = [f for f in self.inv["features"] if f["store"] == "pitcher game logs"][0]["span"]
        self.assertEqual(span["tally"]["sealed_skipped"], 1)
        self.assertEqual(span["tally"]["unparseable"], 0)
        self.assertEqual(span["last"], "2026-09-05")
        self.assertEqual(span["first_unsealed"], "2025-06-01")
        self.assertEqual(self.inv["sealed_skipped"]["pitcher game logs"], 1)

    def test_read_dated_gate_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.jsonl"
            _write_lines(p, [
                '{"date": "2026-01-01", "v": ',                 # first sealed day, unparseable
                '{"date": "2026-08-27", "v": ',                 # last sealed day, unparseable
                {"date": "2026-08-28", "v": 1},                 # first day after: before --since
                {"date": "2026-09-10", "v": 2},
                '{"nodate": 1}',
            ])
            rows, tally = pi.read_dated(p, "date", "2026-09-10")
            self.assertEqual([r["v"] for r in rows], [2])
            self.assertEqual(tally["sealed_skipped"], 2)
            self.assertEqual(tally["pre_window"], 1)
            self.assertEqual(tally["undated"], 1)
            self.assertEqual(tally["unparseable"], 0)

    def test_since_inside_sealed_window_refused(self):
        with self.assertRaises(SystemExit):
            pi.main(["--root", self.root, "--since", "2026-08-01"])

    # -- credits --------------------------------------------------------------

    def test_credit_spend_from_drops(self):
        days = self.inv["credit_days"]
        self.assertEqual(days["2026-09-12"]["spend"], 150)    # 1000->900->850
        self.assertEqual(days["2026-09-13"]["spend"], 10)     # 850->840
        self.assertEqual(self.inv["credit_live_per_day"], {"2026-09-12": 1})
        self.assertEqual(self.inv["marker_pitcher_k"]["fetches"], 1)
        self.assertEqual(self.inv["marker_pitcher_k"]["credits"], 1)
        self.assertEqual(self.inv["marker_batter"]["distribution"], {5: 1})

    def test_cost_model(self):
        self.assertEqual(pi.cost_per_game(4), 4)
        self.assertEqual(pi.cost_per_game(4, regions=2, snapshots=3), 24)

    # -- read-only -----------------------------------------------------------

    def test_inputs_untouched_and_markdown_renders(self):
        text = pi.render_markdown(self.inv)
        self.assertIn("Table 1", text)
        self.assertNotIn("nan", text.lower().replace("finance", ""))
        self.assertEqual(self.before, _tree_hashes(self.root))

    def test_update_doc_replaces_only_between_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "d.md"
            doc.write_text("HEAD\n%s\nOLD\n%s\nTAIL\n" % (pi.GEN_BEGIN, pi.GEN_END),
                           encoding="utf-8")
            pi.update_doc(doc, "NEW")
            self.assertEqual(doc.read_text(encoding="utf-8"),
                             "HEAD\n%s\nNEW\n%s\nTAIL\n" % (pi.GEN_BEGIN, pi.GEN_END))


if __name__ == "__main__":
    unittest.main()
