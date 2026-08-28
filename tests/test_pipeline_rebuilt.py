"""Tests for src/pipeline/rebuilt.py — the point-in-time replacements.

The property that matters: a cutoff is a FILTER over rows that carry their own
dates. Move the cutoff earlier and data disappears; nothing from at-or-after
the cutoff can ever appear. That is the exact property the leaky endpoints
failed, so it is what gets tested.
"""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import rebuilt
from src.providers import statcast_pitches as sp


def pitch(date, pitcher="1", batter="9", stand="R", pitch_type="FF",
          description="hit_into_play", events=None, woba=None, denom=None):
    return {"game_date": date, "pitcher": pitcher, "batter": batter,
            "stand": stand, "p_throws": "R", "pitch_type": pitch_type,
            "description": description, "events": events,
            "woba_value": woba, "woba_denom": denom,
            "release_speed": "94.0", "game_pk": "1", "at_bat_number": "1",
            "pitch_number": "1", "inning": "1", "home_team": "NYY",
            "away_team": "BOS"}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def write(self, key, rows):
        manifest = sp.read_manifest(self.store)
        path = self.store / f"pitches_{key}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        manifest["windows"][key] = {"rows": len(rows), "file": path.name}
        (self.store / "manifest.json").write_text(json.dumps(manifest))


class TestTheCutoffIsAFilter(StoreCase):

    def test_rows_at_or_after_the_cutoff_never_appear(self):
        self.write("2023-04-01..2023-04-04", [
            pitch("2023-04-01"), pitch("2023-04-03"), pitch("2023-04-04")])
        seen = [r["game_date"] for r in sp.iter_rows(self.store,
                                                     before="2023-04-03")]
        self.assertEqual(seen, ["2023-04-01"])

    def test_a_window_starting_at_the_cutoff_is_never_opened(self):
        # Windows are date-sorted, so iteration can stop entirely rather than
        # reading and discarding -- but the observable contract is the same.
        self.write("2023-04-01..2023-04-04", [pitch("2023-04-01")])
        self.write("2023-05-01..2023-05-04", [pitch("2023-05-01")])
        seen = list(sp.iter_rows(self.store, before="2023-05-01"))
        self.assertEqual(len(seen), 1)

    def test_moving_the_cutoff_earlier_only_removes_data(self):
        self.write("2023-04-01..2023-04-04",
                   [pitch("2023-04-01", events="single", woba="0.9", denom="1"),
                    pitch("2023-04-03", events="single", woba="0.9", denom="1")])
        late = rebuilt.accumulate("2023-04-04", self.store)
        early = rebuilt.accumulate("2023-04-02", self.store)
        self.assertEqual(late["matchup"][("9", "1")]["ab"], 2)
        self.assertEqual(early["matchup"][("9", "1")]["ab"], 1)


class TestPlatoonSplit(StoreCase):

    def rows(self, n_left=70, n_right=70, left_woba=0.9, right_woba=0.1):
        out = []
        for i in range(n_left):
            out.append(pitch("2023-04-01", stand="L", events="single",
                             woba=str(left_woba), denom="1", batter=str(100 + i)))
        for i in range(n_right):
            out.append(pitch("2023-04-01", stand="R", events="field_out",
                             woba=str(right_woba), denom="1", batter=str(200 + i)))
        return out

    def test_a_real_split_reports_direction_and_samples(self):
        self.write("2023-04-01..2023-04-04", self.rows())
        acc = rebuilt.accumulate("2023-05-01", self.store)
        split = rebuilt.platoon_split(acc, 1)
        self.assertTrue(split["usable"])
        self.assertEqual(split["weaker_against"], "L")
        self.assertEqual(split["vs_left_faced"], 70)

    def test_the_sample_floor_matches_the_live_version(self):
        # A rebuilt feature gating differently from its live twin makes
        # historical and forward results incomparable.
        self.write("2023-04-01..2023-04-04", self.rows(n_left=59))
        acc = rebuilt.accumulate("2023-05-01", self.store)
        split = rebuilt.platoon_split(acc, 1)
        self.assertFalse(split["usable"])
        self.assertIn("59 batters faced", split["reason"])
        from src.pipeline import lineups
        self.assertEqual(rebuilt.MIN_BF_PER_SIDE, lineups.MIN_BATTERS_FOR_SPLIT)


class TestPitchMix(StoreCase):

    def test_usage_whiff_and_woba_per_pitch(self):
        rows = ([pitch("2023-04-01", pitch_type="FF",
                       description="swinging_strike") for _ in range(30)]
                + [pitch("2023-04-01", pitch_type="SL",
                         description="called_strike") for _ in range(30)])
        self.write("2023-04-01..2023-04-04", rows)
        acc = rebuilt.accumulate("2023-05-01", self.store)
        mix = rebuilt.pitch_mix(acc, 1)
        ff = [m for m in mix if m["pitch_type"] == "FF"][0]
        self.assertEqual(ff["usage_pct"], 50.0)
        self.assertEqual(ff["whiff_pct"], 100.0)
        sl = [m for m in mix if m["pitch_type"] == "SL"][0]
        self.assertIsNone(sl["whiff_pct"])  # no swings, never divide

    def test_below_the_pitch_floor_the_mix_is_empty(self):
        self.write("2023-04-01..2023-04-04",
                   [pitch("2023-04-01") for _ in range(20)])
        acc = rebuilt.accumulate("2023-05-01", self.store)
        self.assertEqual(rebuilt.pitch_mix(acc, 1), [])


class TestMatchupHistory(StoreCase):

    def test_counts_and_average(self):
        self.write("2023-04-01..2023-04-04", [
            pitch("2023-04-01", events="single", woba="0.9", denom="1"),
            pitch("2023-04-02", events="strikeout", woba="0", denom="1"),
            pitch("2023-04-03", events="walk", woba="0.7", denom="1")])
        acc = rebuilt.accumulate("2023-05-01", self.store)
        line = rebuilt.batter_vs_pitcher(acc, 9, 1)
        self.assertEqual(line["at_bats"], 2)   # the walk is not an at-bat
        self.assertEqual(line["hits"], 1)
        self.assertEqual(line["strikeouts"], 1)
        self.assertEqual(line["avg"], 0.5)

    def test_an_unseen_pair_is_zero_at_bats_not_an_error(self):
        self.write("2023-04-01..2023-04-04", [pitch("2023-04-01")])
        acc = rebuilt.accumulate("2023-05-01", self.store)
        self.assertEqual(rebuilt.batter_vs_pitcher(acc, 999, 998)["at_bats"], 0)


class TestExportCapIsAnError(unittest.TestCase):

    def test_hitting_the_cap_raises_rather_than_storing_a_truncation(self):
        # A window missing its last day looks complete. That is why the cap is
        # treated as data loss and not as a big result.
        import unittest.mock as mock
        rows = "game_date\n" + "\n".join(["2023-04-01"] * sp.EXPORT_CAP)
        with mock.patch("urllib.request.urlopen") as fake:
            fake.return_value.__enter__.return_value.read.return_value = \
                rows.encode()
            with self.assertRaises(sp.StatcastPitchError) as ctx:
                sp.fetch_window("2023-04-01", "2023-04-04")
        self.assertIn("truncated", str(ctx.exception))


class TestBuildSnapshots(StoreCase):
    """build_snapshots must be indistinguishable from accumulate per cutoff."""

    def seed(self):
        # Rows straddle the monthly boundaries, and the May window's rows are
        # written OUT of date order to prove ordering does not depend on how
        # Savant happened to return the feed.
        self.write("2023-04-28..2023-05-01", [
            pitch("2023-04-28", events="single", woba="0.9", denom="1"),
            pitch("2023-04-30", events="strikeout", woba="0", denom="1"),
            pitch("2023-05-01", events="double", woba="1.25", denom="1")])
        self.write("2023-05-29..2023-06-01", [
            pitch("2023-06-01", events="home_run", woba="2.0", denom="1"),
            pitch("2023-05-30", events="field_out", woba="0", denom="1"),
            pitch("2023-05-29", events="single", woba="0.9", denom="1",
                  pitch_type="SL", description="swinging_strike")])

    def test_each_snapshot_equals_the_per_cutoff_accumulation(self):
        self.seed()
        cutoffs = ["2023-05-01", "2023-06-01", "2023-07-01"]
        snaps = rebuilt.build_snapshots(cutoffs, store=self.store)
        for cutoff in cutoffs:
            self.assertEqual(snaps[cutoff],
                             rebuilt.accumulate(cutoff, self.store))

    def test_rows_on_the_cutoff_date_are_excluded(self):
        self.seed()
        snaps = rebuilt.build_snapshots(["2023-05-01"], store=self.store)
        # 04-28 single + 04-30 strikeout only; the 05-01 double must not leak.
        self.assertEqual(snaps["2023-05-01"]["matchup"][("9", "1")],
                         {"ab": 2, "hits": 1, "k": 1, "value": 0.9,
                          "denom": 2})

    def test_datetime_cutoffs_reduce_to_the_calendar_day(self):
        # The datetime-vs-date case iter_rows guards: str(datetime) sorts
        # after the bare date and would admit the cutoff day's own pitches.
        from datetime import datetime
        self.seed()
        cutoff = datetime(2023, 5, 1, 19, 5)
        snaps = rebuilt.build_snapshots([cutoff], store=self.store)
        acc = rebuilt.accumulate(cutoff, self.store)
        self.assertEqual(snaps[str(cutoff)], acc)
        self.assertEqual(snaps[str(cutoff)]["matchup"][("9", "1")]["ab"], 2)

    def test_snapshots_are_independent_of_later_mutation(self):
        self.seed()
        snaps = rebuilt.build_snapshots(["2023-05-01", "2023-07-01"],
                                        store=self.store)
        expected = rebuilt.accumulate("2023-05-01", self.store)
        # Deep-mutate the later snapshot; the earlier one must not move.
        snaps["2023-07-01"]["matchup"][("9", "1")]["ab"] = 999
        snaps["2023-07-01"]["arsenal"]["1"]["FF"]["pitches"] = 999
        snaps["2023-07-01"]["pitcher_vs"][("1", "R")]["bf"] = 999
        self.assertEqual(snaps["2023-05-01"], expected)

    def test_unsorted_cutoffs_and_one_past_all_data(self):
        self.seed()
        snaps = rebuilt.build_snapshots(["2024-01-01", "2023-04-30"],
                                        store=self.store)
        self.assertEqual(snaps["2023-04-30"],
                         rebuilt.accumulate("2023-04-30", self.store))
        self.assertEqual(snaps["2024-01-01"],
                         rebuilt.accumulate("2024-01-01", self.store))
        # Past every stored row, the snapshot sees the full store.
        self.assertEqual(snaps["2024-01-01"]["matchup"][("9", "1")]["ab"], 6)


if __name__ == "__main__":
    unittest.main()


class TestBatterVsPitchType(StoreCase):

    def test_accumulates_across_pitchers(self):
        # The lineup-vs-pitch read spans every pitcher the hitter has faced,
        # not just tonight's starter.
        self.write("2023-04-01..2023-04-04", [
            pitch("2023-04-01", pitcher="1", pitch_type="SL",
                  events="single", woba="0.9", denom="1"),
            pitch("2023-04-02", pitcher="2", pitch_type="SL",
                  events="field_out", woba="0", denom="1")])
        acc = rebuilt.accumulate("2023-05-01", self.store)
        line = rebuilt.batter_vs_pitch_type(acc, 9, "SL")
        self.assertEqual(line["pa"], 2)
        self.assertEqual(line["woba"], 0.45)

    def test_an_unseen_combination_is_zero_pa_with_no_invented_woba(self):
        self.write("2023-04-01..2023-04-04", [pitch("2023-04-01")])
        acc = rebuilt.accumulate("2023-05-01", self.store)
        line = rebuilt.batter_vs_pitch_type(acc, 9, "KN")
        self.assertEqual(line["pa"], 0)
        self.assertIsNone(line["woba"])
