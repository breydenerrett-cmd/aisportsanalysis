"""The raw-capture lookup reads each capture once per run and answers as before.

MEASURED 2026-10-01 on a runner's stores: `l1._match_raw` listed the day's
raw directory and re-opened and re-parsed every capture in the match window
once per observation -- 191,052 observations against 233 files was 1,273 of
the 1,286 seconds `engine slate` took, twice per capture slot. `_RawIndex`
does that work once per run. These tests hold the two things that matter:
the answer is the one the per-observation walk gave (the old walk is kept
here, verbatim, as the reference), and the files are read once.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.board import l1


def _reference_match_raw(obs: dict, raw_root: Path):
    """`l1._match_raw` as it stood before the index (2026-10-01), unchanged."""
    day = l1._row_date(obs)
    observed = l1._parse_iso(obs["observed_utc"]) if obs.get("observed_utc") else None
    if observed is None:
        return False, None
    for candidate_day in {day, (observed - timedelta(days=1)).date().isoformat()}:
        for path in l1._iter_raw_files(raw_root, candidate_day):
            capture_id = path.stem.split(".")[0]
            try:
                captured_stamp = capture_id.split("-")[0]
                captured_at = datetime.strptime(
                    captured_stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if abs((captured_at - observed).total_seconds()) > l1.RAW_MATCH_WINDOW_SECONDS:
                continue
            record = l1._load_raw_capture(path)
            if not record:
                continue
            want_name = l1._OUTCOME_NAME_BY_SIDE.get(obs["side"])
            for outcome, _last_update in l1._raw_outcomes(
                    record.get("payload"), obs["event_id"], obs["book"],
                    obs["provider_market_key"]):
                name = outcome.get("name")
                if want_name is not None and name != want_name:
                    continue
                if outcome.get("price") == obs["price_american"]:
                    return True, capture_id
    return False, None


def _event(event_id, book, market, outcomes):
    return {"id": event_id, "bookmakers": [
        {"key": book, "last_update": "x", "markets": [{"key": market, "outcomes": outcomes}]}]}


def _write_capture(root: Path, stamp: str, suffix: str, payload, *, raw_text=None) -> None:
    day_dir = root / stamp[0:4] / stamp[4:6] / stamp[6:8]
    day_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(day_dir / f"{stamp}-{suffix}.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.write(raw_text if raw_text is not None else json.dumps({"payload": payload}) + "\n")


def _obs(observed_utc, event_id="ev1", book="bk1", market="h2h", side="home", price=-110):
    return {"observed_utc": observed_utc, "event_id": event_id, "book": book,
            "provider_market_key": market, "side": side, "price_american": price}


class RawIndexFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        h2h = [{"name": "Home Club", "price": -110}, {"name": "Away Club", "price": 100}]
        totals = [{"name": "Over", "price": -105, "point": 8.5},
                  {"name": "Under", "price": -115, "point": 8.5}]
        # Two captures a minute apart: some observations are in both windows, some in one.
        _write_capture(self.root, "20261001T120100Z", "aaa", [_event("ev1", "bk1", "h2h", h2h)])
        _write_capture(self.root, "20261001T120000Z", "zzz", [_event("ev1", "bk1", "h2h", h2h),
                                                              _event("ev1", "bk1", "totals", totals)])
        # Exactly on the window edge, one second past it, and a different price.
        _write_capture(self.root, "20261001T130000Z", "edge", [_event("ev2", "bk1", "h2h", h2h)])
        _write_capture(self.root, "20261001T140000Z", "moved",
                       [_event("ev1", "bk1", "h2h", [{"name": "Home Club", "price": -125}])])
        # The day before, close to midnight; a payload that is one event, not a list.
        _write_capture(self.root, "20260930T235930Z", "late", _event("ev3", "bk2", "h2h", h2h))
        # Files the walk skips: a name that is not a timestamp, an empty file, broken JSON.
        _write_capture(self.root, "notatimestamp", "x", [], raw_text="{}\n")
        _write_capture(self.root, "20261001T120030Z", "empty", None, raw_text="\n")
        _write_capture(self.root, "20261001T120040Z", "broken", None, raw_text="{not json\n")
        self.observations = [
            _obs("2026-10-01T12:00:30Z"),                                   # two candidates
            _obs("2026-10-01T12:00:30.250000Z"),                            # fractional seconds
            _obs("2026-10-01T12:02:30Z"),                                   # only the later capture
            _obs("2026-10-01T12:00:10Z", market="totals", side="over", price=-105),
            _obs("2026-10-01T12:00:10Z", market="totals", side="under", price=-105),  # name mismatch
            _obs("2026-10-01T12:00:10Z", market="totals", side="under", price=-115),
            _obs("2026-10-01T13:02:00Z", event_id="ev2"),                   # exactly 120 s: inside
            _obs("2026-10-01T13:02:01Z", event_id="ev2"),                   # 121 s: outside
            _obs("2026-10-01T12:58:00Z", event_id="ev2"),                   # 120 s before: inside
            _obs("2026-10-01T14:00:05Z"),                                   # price moved: no match
            _obs("2026-10-01T14:00:05Z", price=-125),
            _obs("2026-10-01T00:00:20Z", event_id="ev3", book="bk2"),       # matches yesterday's file
            _obs("2026-10-01T12:00:30Z", event_id="nobody"),
            _obs("2026-10-01T12:00:30Z", book="other"),
            _obs("2026-10-03T12:00:30Z"),                                   # a day with no directory
            _obs(None),
        ]

    def test_every_observation_gets_the_answer_the_old_walk_gave(self):
        index = l1._RawIndex(self.root)
        for obs in self.observations:
            expected = _reference_match_raw(obs, self.root)
            self.assertEqual(l1._match_raw(obs, self.root, index), expected, obs)
            self.assertEqual(l1._match_raw(obs, self.root), expected, obs)

    def test_the_fixture_exercises_both_outcomes(self):
        answers = [_reference_match_raw(obs, self.root) for obs in self.observations]
        self.assertIn((True, "20261001T120000Z-zzz"), answers)
        self.assertIn((True, "20261001T120100Z-aaa"), answers)
        self.assertIn((True, "20260930T235930Z-late"), answers)
        self.assertIn((True, "20261001T130000Z-edge"), answers)
        self.assertGreaterEqual(answers.count((False, None)), 6)

    def test_a_capture_is_opened_once_however_many_observations_ask(self):
        opened = []
        real_open = gzip.open

        def counting(path, *args, **kwargs):
            opened.append(Path(path).name)
            return real_open(path, *args, **kwargs)

        index = l1._RawIndex(self.root)
        with mock.patch.object(l1.gzip, "open", counting):
            for _ in range(50):
                for obs in self.observations:
                    l1._match_raw(obs, self.root, index)
        self.assertEqual(len(opened), len(set(opened)), sorted(opened))
        self.assertGreater(len(opened), 0)

    def test_the_directory_is_listed_once_per_day(self):
        listed = []
        real_iter = l1._iter_raw_files

        def counting(raw_root, day):
            listed.append(day)
            return real_iter(raw_root, day)

        index = l1._RawIndex(self.root)
        with mock.patch.object(l1, "_iter_raw_files", counting):
            for _ in range(20):
                for obs in self.observations:
                    l1._match_raw(obs, self.root, index)
        self.assertEqual(len(listed), len(set(listed)), listed)

    def test_run_shares_one_index_across_every_store(self):
        store = self.root / "store.jsonl"
        rows = [{"observed_utc": "2026-10-01T12:00:30Z", "event_id": "ev1", "book": "bk1",
                 "market": "h2h", "home_price": -110, "away_price": 100,
                 "home_team": "Home Club", "away_team": "Away Club",
                 "commence_time": "2026-10-01T23:00:00Z"}] * 3
        store.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        built = []
        real_index = l1._RawIndex

        def counting(raw_root):
            built.append(raw_root)
            return real_index(raw_root)

        sources = [{"name": n, "path": store, "kind": "multibook", "is_close": False}
                   for n in ("store_a", "store_b")]
        with mock.patch.object(l1, "_RawIndex", counting):
            l1.run(since="2026-10-01", output_path=self.root / "out.jsonl", raw_root=self.root,
                   sources=sources, game_map_path=None)
        self.assertEqual(len(built), 1)


if __name__ == "__main__":
    unittest.main()
