"""Model inputs stay exactly what they were: regular season only (2026-10-03).

THE DEFECT. The display refresh (src/pipeline/display_refresh.py) stores the
postseason in the pitcher-log file, each start tagged with its `game_type`, so
the postseason page can show October. The same file is read by every consumer
that turns it into a model input: starter features on the game pages, the live
card preview, the analyst packet, the postseason page's pricing and the CLI
commands. A postseason start is a different, selected population (the best
clubs, aces starting, no regular-season fatigue), and measured on a synthetic
starter one Wild Card start moved his ERA from 3.00 to 6.39 and changed the
card's pick for the game. The review found it before it shipped.

THE RULE, PINNED HERE. Every consumer that feeds a model or a price reads the
regular-season view (`pitchers.regular_season_logs`), applied AT THE CONSUMER.
It is never applied inside `pitchers.read_logs`: `build_log_store` rewrites the
whole file from `read_logs`, so a filter there would delete the postseason
rows on the next refresh.

What is proved:
  * the view is a pure copy that drops tagged non-regular rows and nothing else
  * `read_logs` and a refresh round trip still keep every row
  * on a store holding BOTH, every model input equals what the regular-season
    only store gives: the enrichment inputs, the starters and teams sections,
    the card's features and its published payload (byte for byte), and the
    postseason page's whole payload
No network; temp files and injected stores only.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.analysis import opportunities
from src.pipeline import (briefing, bullpen, enrichment, features as team_features,
                          pitchers)
from src.providers import mlb
from src.report import card as card_mod
from tests._fake_statsapi import FakeStatsApi
from tests.test_postseason_page import (_rotation, build as build_postseason_page,
                                        pitcher_logs as postseason_logs, schedule_game)

DATE = "2026-10-03"
NOW = datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)
OBSERVED = datetime(2026, 10, 3, 13, 30, tzinfo=timezone.utc)


def _appearance(pid, day, *, ip=6.0, er=2, game_type=None, k=6, bb=1, hr=1):
    row = {"person_id": pid, "date": day, "season": day[:4], "games_started": 1,
           "innings_pitched": ip, "earned_runs": er, "runs": er, "hits": 5, "walks": bb,
           "strikeouts": k, "home_runs": hr, "batters_faced": 24, "pitches": 90}
    if game_type:
        row["game_type"] = game_type
    return row


def _marker(pid, checked_utc="2026-10-03T10:00:00+00:00"):
    return {"person_id": pid, "season": "2026", "date": None, "empty": False,
            "checked_utc": checked_utc}


def _logs(with_postseason):
    """Two starters. The postseason rows are deliberately awful (one inning,
    seven or eight earned runs) so that any leak moves every rate."""
    out = {}
    for pid, base_er in ((111, 2), (222, 3)):
        rows = [_appearance(pid, f"2026-09-{d:02d}", er=base_er, game_type="R" if d % 2 else None)
                for d in (3, 8, 13, 18, 23, 27)]
        if with_postseason:
            rows += [_appearance(pid, "2026-09-30", ip=1.0, er=8, game_type="F", k=0, bb=4, hr=3),
                     _appearance(pid, "2026-10-01", ip=1.0, er=7, game_type="D", k=0, bb=3, hr=2)]
        rows.append(_marker(pid))
        out[str(pid)] = rows
    return out


def _store():
    rows, pk = {}, 0
    for day in range(1, 30):
        date = f"2026-09-{day:02d}"
        for away, home, a, h in (("NYY", "BOS", 4, 3), ("BOS", "NYY", 2, 5), ("LAD", "SD", 3, 1)):
            pk += 1
            rows[str(pk)] = {"game_pk": str(pk), "date": date, "game_type": "R", "away_team": away,
                             "home_team": home, "away_score": str(a), "home_score": str(h),
                             "winner": away if a > h else home, "home_won": "1" if h > a else "0",
                             "total_runs": str(a + h), "run_differential": str(abs(a - h))}
    return rows


def _game():
    return {"game_pk": 880001, "away_team": "NYY", "home_team": "BOS", "date": DATE,
            "start_time_utc": f"{DATE}T23:05:00Z", "venue": "Fenway Park",
            "away_probable_id": 111, "home_probable_id": 222,
            "away_probable": "Away Starter", "home_probable": "Home Starter"}


class _Calibration:
    """Stands in for the fitted calibration file, so nothing is read from disk."""
    n = 0

    def apply(self, p):
        return p

    def to_dict(self):
        return {"stub": True}


def _stores_patched(stack: ExitStack, logs):
    """Every store `enrichment_inputs` reads, injected: nothing touches data/."""
    for target, name, value in (
            (pitchers, "read_logs", logs),
            (bullpen, "read_log", []),
            (enrichment.lineup_store, "read", {}),
            (enrichment.lineups, "read_handedness", {}),
            (enrichment.lineups, "read_splits", {}),
            (enrichment.standings, "read", {}),
            (enrichment.matchup_history, "read", {}),
            (enrichment.weather_capture, "read", []),
            (enrichment.news, "read", []),
            (enrichment.statcast, "read", {"rows": []})):
        stack.enter_context(mock.patch.object(target, name, return_value=value))


def _card_for(entries):
    """The card exactly as `card publish` builds it from a slate's entries."""
    opps = opportunities.build_opportunities(entries, date=DATE, now=NOW)
    return card_mod.card_for_date(
        entries, opps["rows"], date=DATE, now=NOW, prefer_frozen=False,
        calibration=_Calibration(), multibook_rows=[], event_map={},
        prop_board=lambda d: {"contracts": [], "reason": "n/a"})


def _slate(logs):
    """The slate and the card, built the way the API and `card publish` build
    them: `enrichment_inputs`, then `build_slate`, then the card."""
    board = {("NYY", "BOS", DATE): {
        "quotes": [{"ts": OBSERVED.isoformat(), "book": book, "away_price": 105 + i,
                    "home_price": -125 - i} for i, book in enumerate("abcdefg")],
        "observed_utc": OBSERVED.isoformat(), "source": "test"}}
    game, store = _game(), _store()
    with ExitStack() as stack:
        _stores_patched(stack, logs)
        inputs = enrichment.enrichment_inputs([game], DATE, store)
        inputs.update(price_boards_by_key=board, roster_events_by_pk={})
        entries = briefing.build_slate([game], store, **inputs)["games"]
    return inputs, entries, _card_for(entries)


class TheViewIsAPureCopy(unittest.TestCase):

    def test_tagged_postseason_rows_go_and_everything_else_stays(self):
        logs = _logs(with_postseason=True)
        view = pitchers.regular_season_logs(logs)
        for pid in ("111", "222"):
            kept = view[pid]
            self.assertEqual({a.get("game_type") for a in kept}, {None, "R"})
            self.assertEqual(sum(1 for a in kept if a.get("date")), 6)
            self.assertEqual([a for a in kept if a.get("date") is None], [_marker(int(pid))],
                             "the refresh marker is coverage, not a start: it stays")

    def test_every_postseason_code_is_left_out(self):
        rows = [_appearance(1, f"2026-10-{i:02d}", game_type=code)
                for i, code in enumerate(("F", "D", "L", "W", "P"), 1)]
        rows.append(_appearance(1, "2026-09-27"))
        self.assertEqual([a["date"] for a in pitchers.regular_season_logs({"1": rows})["1"]],
                         ["2026-09-27"])

    def test_the_input_is_not_modified(self):
        logs = _logs(with_postseason=True)
        before = json.dumps(logs, sort_keys=True)
        view = pitchers.regular_season_logs(logs)
        self.assertEqual(json.dumps(logs, sort_keys=True), before)
        self.assertIsNot(view["111"], logs["111"])

    def test_a_pitcher_left_with_nothing_is_absent_like_in_a_store_that_never_held_him(self):
        logs = {"7": [_appearance(7, "2026-10-01", game_type="D")], "8": [_appearance(8, "2026-09-20")]}
        self.assertEqual(sorted(pitchers.regular_season_logs(logs)), ["8"])

    def test_empty_and_missing_logs_are_fine(self):
        self.assertEqual(pitchers.regular_season_logs({}), {})
        self.assertEqual(pitchers.regular_season_logs(None), {})


class TheStoreStillKeepsEveryRow(unittest.TestCase):
    """The filter lives at the consumers. If it ever moved into `read_logs`,
    `build_log_store` (which rewrites the file from it) would delete October."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "pitcher_logs.jsonl"

    def test_read_logs_returns_the_postseason_rows(self):
        pitchers.write_logs(_logs(with_postseason=True), self.path)
        rows = pitchers.read_logs(self.path)["111"]
        self.assertEqual({a.get("game_type") for a in rows if a.get("date")}, {None, "R", "F", "D"})

    def test_a_refresh_round_trip_keeps_the_postseason_rows(self):
        fake = FakeStatsApi(schedule={}, game_logs={111: [
            {"date": "2026-09-27", "gameType": "R"},
            {"date": "2026-09-29", "gameType": "F"},
            {"date": "2026-10-01", "gameType": "D"}]})
        pitchers.write_logs({"111": [_appearance(111, "2026-09-27")]}, self.path)
        with mock.patch.object(mlb, "_get_json", fake):
            for hours in (0.0, 0.0):          # two refreshes in a row
                pitchers.build_log_store(
                    [111], "2026", path=self.path, resume=True, refresh=True,
                    refresh_after_hours=hours, now=NOW, game_types=mlb.DECISIVE_GAME_TYPES)
        stored = pitchers.read_logs(self.path)["111"]
        self.assertEqual(sorted(a["game_type"] for a in stored if a.get("date")), ["D", "F", "R"])


class EveryModelInputEqualsTheRegularSeasonStore(unittest.TestCase):
    """The store holding both must give every model the same input as the
    store holding the regular season only."""

    @classmethod
    def setUpClass(cls):
        cls.both = _slate(_logs(with_postseason=True))
        cls.regular = _slate(_logs(with_postseason=False))

    def test_the_premise_a_postseason_start_would_move_the_numbers(self):
        # Computed on the raw rows, with no filter: the leak this guards.
        raw_both = _logs(with_postseason=True)
        raw_regular = _logs(with_postseason=False)
        leaked = pitchers.matchup_pitcher_features(raw_both, 111, 222, DATE)
        clean = pitchers.matchup_pitcher_features(raw_regular, 111, 222, DATE)
        self.assertNotEqual(leaked["away_sp_era"], clean["away_sp_era"])
        self.assertNotEqual(leaked["away_sp_days_rest"], clean["away_sp_days_rest"])

    def test_the_enrichment_inputs_hand_build_slate_the_same_logs(self):
        both_logs = self.both[0]["pitcher_logs"]
        regular_logs = self.regular[0]["pitcher_logs"]
        # Same rows, same order, same content. (The regular-season store here
        # tags some rows "R" and some not; a postseason tag never survives.)
        self.assertEqual(json.dumps(both_logs, sort_keys=True),
                         json.dumps(regular_logs, sort_keys=True))
        for rows in both_logs.values():
            self.assertTrue(all(pitchers.is_regular_season(a) for a in rows))

    def test_the_starters_and_teams_sections_are_identical(self):
        for section in ("starters", "teams"):
            self.assertEqual(self.both[1][0]["dossier"].sections[section],
                             self.regular[1][0]["dossier"].sections[section], section)

    def test_the_starter_features_are_what_the_regular_season_alone_gives(self):
        feats = self.both[1][0]["dossier"].sections["starters"]
        direct = pitchers.matchup_pitcher_features(_logs(with_postseason=False), 111, 222, DATE)
        self.assertEqual(feats, direct)
        # and the numbers a person would see: his last start is the 27th
        self.assertEqual(feats["away_sp_days_rest"], 6)
        self.assertEqual(feats["away_sp_starts"], 6)

    def test_the_card_features_and_the_published_payload_are_byte_identical(self):
        self.assertEqual(card_mod._flatten(self.both[1][0]), card_mod._flatten(self.regular[1][0]))
        both, regular = (json.dumps(p[2], sort_keys=True, default=str)
                         for p in (self.both, self.regular))
        self.assertEqual(both, regular)

    def test_the_card_payload_is_a_real_one_with_a_pick_priced_by_the_model(self):
        picks = self.both[2]["picks"]
        self.assertEqual(len(picks), 1, self.both[2].get("reason"))
        self.assertIsNotNone(picks[0]["model_probability"])


class ThePostseasonPageIsPricedFromTheRegularSeasonAlone(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rotation = _rotation("A5")[1], _rotation("A4")[1]
        cls.probables = [schedule_game(1, "2026-10-01", "A5", "A4", *rotation)]
        regular = postseason_logs()
        both = postseason_logs()
        # Every rotation starter also made two awful, tagged postseason starts.
        for pid, rows in both.items():
            for day, code in (("2026-09-29", "F"), ("2026-09-30", "F")):
                rows.append({"person_id": int(pid), "date": day, "season": "2026",
                             "game_type": code, "games_started": 1, "innings_pitched": 1.0,
                             "earned_runs": 9, "runs": 9, "hits": 9, "walks": 6, "strikeouts": 0,
                             "home_runs": 4, "batters_faced": 20, "pitches": 60})
            rows.sort(key=lambda r: r["date"])
        cls.both_logs, cls.regular_logs = both, regular
        cls.page_both = build_postseason_page(pitcher_logs=both, probables=cls.probables)
        cls.page_regular = build_postseason_page(pitcher_logs=regular, probables=cls.probables)

    def test_the_premise_the_page_is_available_and_prices_a_starter(self):
        self.assertTrue(self.page_regular["available"], self.page_regular.get("reason"))
        game = next(g for s in self.page_regular["series"] for g in s["games"]
                    if g.get("starter_input_class") == "CONFIRMED_CURRENT")
        self.assertIsNotNone(game)

    def test_the_whole_payload_is_identical_with_or_without_the_postseason_rows(self):
        self.assertEqual(json.dumps(self.page_both, sort_keys=True, default=str),
                         json.dumps(self.page_regular, sort_keys=True, default=str))

    def test_the_caller_s_logs_are_not_modified(self):
        # the page filters a copy; the store a caller holds keeps its rows
        self.assertTrue(any(a.get("game_type") == "F"
                            for rows in self.both_logs.values() for a in rows))

    def test_a_fetcher_that_returns_tagged_postseason_rows_cannot_smuggle_them_in(self):
        pid = _rotation("A5")[1]
        stale = postseason_logs(last_day=10)            # so the starter is not current
        tagged = [{"person_id": pid, "date": d, "season": "2026", "game_type": code,
                   "games_started": 1, "innings_pitched": ip, "earned_runs": er, "runs": er,
                   "hits": 5, "walks": 2, "strikeouts": 6, "home_runs": 1,
                   "batters_faced": 24, "pitches": 90}
                  for d, code, ip, er in (("2026-09-27", None, 6.0, 2), ("2026-09-29", "F", 0.1, 9))]
        for row in tagged:
            if row["game_type"] is None:
                del row["game_type"]
        plain = [r for r in tagged if "game_type" not in r]

        def page_for(rows):
            return build_postseason_page(
                pitcher_logs=stale, probables=self.probables,
                fresh_pitcher_logs=lambda p: rows if p == pid else None)

        self.assertEqual(json.dumps(page_for(tagged), sort_keys=True, default=str),
                         json.dumps(page_for(plain), sort_keys=True, default=str))


class TheCommandLineFeedsModelsTheSameView(unittest.TestCase):
    """cli.py loads the store for four commands that build model inputs. The
    test reads the source: each load must go through the regular-season view."""

    def test_no_model_feeding_command_reads_the_raw_store(self):
        source = (Path(__file__).resolve().parent.parent / "src" / "cli.py").read_text(encoding="utf-8")
        loads = [line.strip() for line in source.splitlines() if "pitchers.read_logs()" in line]
        self.assertGreaterEqual(len(loads), 4)
        for line in loads:
            self.assertIn("regular_season_logs", line, line)


if __name__ == "__main__":
    unittest.main()
