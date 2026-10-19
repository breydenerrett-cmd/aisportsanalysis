"""Fan tips (src/hounds/fan_tips.py): the same validation the coach gets, the limits that survive a restart,
and an export that carries no address.

No FastAPI. The clock and the caller are injected, so the limits run without sleeping. The app database is a
temp file, never the real one.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.hounds import fan_tips
from src.hounds.learning import tunables

NOW = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)
CFG = tunables.load()
CHAMP = {"MOVE": 0.03}


class TipTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "app.db"

    def send(self, values=None, nickname=None, caller="1.1.1.1", hound="steamy_setter", now=NOW, champ=None):
        return fan_tips.submit(hound, values if values is not None else {"MOVE": 0.04}, nickname, caller, now=now,
                               db=self.db, tun_cfg=CFG, champion_values=champ if champ is not None else CHAMP,
                               champion_version=1)

    def refused(self, code, **kw):
        with self.assertRaises(fan_tips.TipError) as ctx:
            self.send(**kw)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return ctx.exception


class Validation(TipTestCase):
    def test_a_good_tip_is_stored_and_returns_its_id(self):
        tip = self.send({"MOVE": 0.04}, "Brey 1")
        self.assertTrue(tip["id"].startswith("tip_"))
        self.assertEqual((tip["hound_id"], tip["values"], tip["nickname"]), ("steamy_setter", {"MOVE": 0.04}, "Brey 1"))
        self.assertEqual(fan_tips.count_for("steamy_setter", db=self.db), 1)

    def test_sending_every_dial_is_fine_when_only_some_moved(self):
        # relies on the same rule as the coach: a knob equal to the champion's is not "changed"
        tip = self.send({"GAP": 0.025, "SHRINK": 0.5}, hound="professor_paws", champ={"GAP": 0.02, "SHRINK": 0.5})
        self.assertEqual(tip["values"], {"GAP": 0.025, "SHRINK": 0.5})

    def test_out_of_bounds_off_grid_and_non_numbers_are_refused_with_the_field_named(self):
        e = self.refused("bad_values", values={"MOVE": 0.06})
        self.assertIn("MOVE", e.errors)
        self.assertIn("MOVE", self.refused("bad_values", values={"MOVE": 0.041}).errors)
        self.assertIn("MOVE", self.refused("bad_values", values={"MOVE": "high"}).errors)
        self.assertIn("MOVE", self.refused("bad_values", values={"MOVE": True}).errors)
        self.assertIn("NOPE", self.refused("bad_values", values={"NOPE": 1}).errors)

    def test_a_tip_that_changes_nothing_is_refused(self):
        self.refused("bad_values", values={"MOVE": 0.03})
        self.refused("bad_values", values={})
        self.refused("bad_values", values=[0.04])

    def test_more_than_two_knobs_are_refused(self):
        champ = {"EDGE": 0.025, "MIN_BOOKS": 5}
        # stale_bread_beagle has two knobs; a three-knob dog would need three. Prove the cap with a fake dog.
        cfg = dict(CFG)
        base = CFG["stale_bread_beagle"]
        extra = tunables.Knob(name="X", label="x", kind="int", default=1, lo=1, hi=5, step=1, renders=())
        cfg["three"] = tunables.TunableHound("three", "Three", "mixed", "m", "t", (), (),
                                             {**base.knobs, "X": extra})
        with self.assertRaises(fan_tips.TipError) as ctx:
            fan_tips.submit("three", {"EDGE": 0.03, "MIN_BOOKS": 6, "X": 2}, None, "9.9.9.9", now=NOW, db=self.db,
                            tun_cfg=cfg, champion_values={**champ, "X": 1}, champion_version=1)
        self.assertEqual(ctx.exception.code, "bad_values")
        self.assertIn("at most 2", str(ctx.exception))
        self.assertEqual(fan_tips.count_for("three", db=self.db), 0)

    def test_two_knobs_are_fine(self):
        tip = self.send({"EDGE": 0.03, "MIN_BOOKS": 6}, hound="stale_bread_beagle", champ={"EDGE": 0.025, "MIN_BOOKS": 5})
        self.assertEqual(tip["values"], {"EDGE": 0.03, "MIN_BOOKS": 6})

    def test_a_dog_with_no_dials_cannot_be_tipped(self):
        e = self.refused("not_tunable", hound="coin_flip_collie")
        self.assertEqual(e.status, 404)
        e = self.refused("not_tunable", hound="u-abc123")
        self.assertEqual(e.status, 404)

    def test_an_int_dial_must_be_a_whole_number(self):
        self.assertIn("GAP", self.refused("bad_values", hound="relief_retriever", values={"GAP": 130.5},
                                          champ={"GAP": 120}).errors)

    def test_nicknames(self):
        self.assertIsNone(self.send(nickname=None)["nickname"])
        self.assertIsNone(self.send(nickname="   ", caller="2.2.2.2")["nickname"])
        self.assertEqual(self.send(nickname="  Big   Dave 7 ", caller="3.3.3.3")["nickname"], "Big Dave 7")
        self.refused("bad_nickname", nickname="x" * 21, caller="4.4.4.4")
        self.refused("bad_nickname", nickname="<script>", caller="4.4.4.4")
        self.refused("bad_nickname", nickname="dave!", caller="4.4.4.4")
        self.refused("bad_nickname", nickname="Dave_1", caller="4.4.4.4")
        self.refused("bad_nickname", nickname=12, caller="4.4.4.4")
        self.assertEqual(fan_tips.NICKNAME_MAX, 20)
        self.assertEqual(self.send(nickname="y" * 20, caller="5.5.5.5")["nickname"], "y" * 20)

    def test_a_nickname_goes_through_the_name_blocklist(self):
        from src.hounds import user_spec
        reserved = next(w for w in ("draftkings", "fanduel") if user_spec.text_problem(w))
        self.refused("bad_nickname", nickname=reserved, caller="6.6.6.6")

    def test_a_refused_tip_spends_no_allowance(self):
        for _ in range(5):
            self.refused("bad_values", values={"MOVE": 0.9})
        for _ in range(3):
            self.send()


class RateLimits(TipTestCase):
    def test_three_a_day_per_caller_then_a_429_with_a_retry_time(self):
        for i in range(3):
            self.send(now=NOW + timedelta(minutes=i))
        e = self.refused("rate_limited", now=NOW + timedelta(minutes=10))
        self.assertEqual(e.status, 429)
        # the oldest tip leaves the window 24 h after it was sent: 24 h minus the 10 minutes already waited
        self.assertEqual(e.retry_after, 24 * 3600 - 10 * 60)

    def test_another_caller_is_not_limited_by_the_first(self):
        for _ in range(3):
            self.send(caller="1.1.1.1")
        self.send(caller="2.2.2.2")
        self.refused("rate_limited", caller="1.1.1.1")

    def test_the_window_rolls(self):
        for _ in range(3):
            self.send()
        self.send(now=NOW + timedelta(hours=24, minutes=1))

    def test_sixty_a_day_for_the_whole_site(self):
        for i in range(fan_tips.SITE_PER_DAY):
            self.send(caller=f"10.0.{i // 250}.{i % 250}", now=NOW + timedelta(seconds=i))
        e = self.refused("site_full", caller="99.99.99.99", now=NOW + timedelta(minutes=5))
        self.assertEqual(e.status, 429)
        self.send(caller="99.99.99.99", now=NOW + timedelta(hours=24, minutes=1))

    def test_the_limits_live_in_the_database_not_in_memory(self):
        # in-memory counters die at every hourly redeploy; these are counted from the rows, so a new process
        # (simulated by wiping every module-level container the module owns) still refuses the fourth tip
        for _ in range(3):
            self.send()
        for name, value in vars(fan_tips).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (dict, list, set), f"module-level state: {name}")
        self.refused("rate_limited")

    def test_the_address_is_stored_only_as_a_salted_hash_and_blanked_after_two_days(self):
        self.send(caller="203.0.113.7")
        con = sqlite3.connect(self.db)
        (stored,) = con.execute("SELECT caller_hash FROM hound_tips").fetchone()
        self.assertEqual(len(stored), 64)
        self.assertNotIn("203.0.113.7", stored)
        self.assertNotEqual(stored, fan_tips._caller_hash("", "203.0.113.7"), "an unsalted hash can be looked up")
        self.assertNotIn("203.0.113.7", json.dumps(con.execute("SELECT * FROM hound_tips_meta").fetchall()))
        con.close()
        self.send(caller="203.0.113.8", now=NOW + timedelta(days=2, minutes=1))
        con = sqlite3.connect(self.db)
        rows = con.execute("SELECT created_utc, caller_hash FROM hound_tips ORDER BY created_utc").fetchall()
        con.close()
        self.assertIsNone(rows[0][1])
        self.assertIsNotNone(rows[1][1])


class ReadingAndExport(TipTestCase):
    def test_a_missing_database_reads_as_no_tips_and_is_not_created_by_a_read(self):
        self.assertEqual(fan_tips.count_for("steamy_setter", db=self.db), 0)
        self.assertEqual(fan_tips.latest("steamy_setter", db=self.db), [])
        self.assertEqual(fan_tips.export(db=self.db), [])
        self.assertFalse(self.db.exists())

    def test_latest_is_newest_first_capped_at_twenty_and_carries_nothing_identifying(self):
        for i in range(25):
            self.send(caller=f"7.7.{i}.1", now=NOW + timedelta(minutes=i), nickname=f"Fan{i}")
        got = fan_tips.latest("steamy_setter", db=self.db)
        self.assertEqual(len(got), 20)
        self.assertEqual(got[0]["nickname"], "Fan24")
        self.assertEqual(set(got[0]), {"id", "values", "nickname", "created_utc"})
        self.assertEqual(fan_tips.count_for("steamy_setter", db=self.db), 25)

    def test_the_export_has_the_documented_fields_and_no_address_or_hash(self):
        self.send(caller="198.51.100.9", nickname="Ann")
        (row,) = fan_tips.export(db=self.db)
        self.assertEqual(set(row), {"id", "hound_id", "values", "champion_values", "champion_version", "nickname",
                                    "created_utc"})
        self.assertEqual((row["values"], row["champion_values"], row["champion_version"]),
                         ({"MOVE": 0.04}, {"MOVE": 0.03}, 1))
        text = json.dumps(row)
        self.assertNotIn("198.51.100.9", text)
        self.assertNotRegex(text, r"[0-9a-f]{64}")
        self.assertNotIn("caller", text)

    def test_the_export_is_oldest_first_and_since_is_exclusive(self):
        self.send(caller="a", now=NOW)
        self.send(caller="b", now=NOW + timedelta(hours=1))
        self.send(caller="c", now=NOW + timedelta(hours=2))
        every = fan_tips.export(db=self.db)
        self.assertEqual([r["created_utc"] for r in every], ["2026-10-18T15:00:00Z", "2026-10-18T16:00:00Z",
                                                             "2026-10-18T17:00:00Z"])
        after = fan_tips.export("2026-10-18T16:00:00Z", db=self.db)
        self.assertEqual([r["created_utc"] for r in after], ["2026-10-18T17:00:00Z"])

    def test_since_parsing(self):
        self.assertIsNone(fan_tips.parse_since(None))
        self.assertIsNone(fan_tips.parse_since("  "))
        self.assertEqual(fan_tips.parse_since("2026-10-18T10:00:00-05:00"), "2026-10-18T15:00:00Z")
        self.assertEqual(fan_tips.parse_since("2026-10-18"), "2026-10-18T00:00:00Z")
        with self.assertRaises(fan_tips.TipError):
            fan_tips.parse_since("yesterday")

    def test_tips_are_a_table_nothing_reads_back_into_a_dog(self):
        # the safety story: no module outside this one and the API imports it, so a tip cannot reach a hound
        root = Path(__file__).resolve().parent.parent
        users = []
        for folder in ("src", "api", "scripts"):
            for path in (root / folder).rglob("*.py"):
                if path.name in ("fan_tips.py",):
                    continue
                if "fan_tips" in path.read_text(encoding="utf-8", errors="ignore"):
                    users.append(path.relative_to(root).as_posix())
        self.assertEqual(sorted(users), ["api/hounds_tips.py"], users)


if __name__ == "__main__":
    unittest.main()
