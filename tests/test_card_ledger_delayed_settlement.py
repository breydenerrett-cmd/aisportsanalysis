"""TASK A1 -- delayed settlement through the real ledger entry point.

Pins the state machine `settle()`/`settle_recent()` now run: a pick whose
result is not available yet stays UNRESOLVED (never a permanent zero-profit
VOID), a retry of an already-fully-resolved date never double-counts, an
interrupted/replayed write cannot corrupt the chain or lose a terminal
result, an existing pre-fix ("legacy") settled row still reads without
crashing or being silently reinterpreted, and a correction to one entry is
reflected exactly once in the read-model without ever editing the row it
corrects.

Every test here goes through `settle()`/`settle_recent()` (the real ledger
entry point), not `grade_pick` et al. in isolation -- `tests/test_card_
ledger.py`'s `GradingIsHonest` class already covers the grading helpers
directly. This file also checks `history()`/`record()` (the read-model a
page/API route actually serves), per this task's own instruction to test
both layers.

Every test runs against a temporary ledger path. None of them touch
`evidence/cards_v1.jsonl` -- see tests/test_card_ledger.py's own module
docstring for why.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger


def _card(date="2026-09-10", picks=None, prop_picks=None, total_picks=None):
    return {
        "date": date,
        "rule": card_ledger.KIND_PUBLISHED,
        "basis": "basis sentence",
        "disclaimer": "disclaimer sentence",
        "model_id": "run_expectancy_poisson_v1",
        "calibrated": True,
        "calibration": {"a": 0.03, "b": 0.51, "n": 1896, "fitted": True},
        "filled": 0,
        "games_on_slate": 5,
        "picks": picks if picks is not None else [_pick()],
        "prop_picks": prop_picks or [],
        "total_picks": total_picks or [],
    }


def _pick(rank=1, market="moneyline", side="home", price=-150, line=None,
         game_pk=1001, label="STRONG"):
    return {
        "rank": rank, "label": label, "bet": f"Take game {game_pk} home side",
        "why": ["because"], "market": market, "line": line, "side": side,
        "team": "NYY", "team_name": "Yankees", "opponent_name": "Rockies",
        "price": price, "book": "draftkings", "books": 8,
        "confidence": 0.74, "market_probability": 0.74,
        "model_probability": 0.64, "game_id": f"COL-NYY-2026-09-10-{game_pk}",
        "game_pk": game_pk, "event_id": "e1", "away_team": "COL",
        "home_team": "NYY", "first_pitch_utc": "2026-09-10T23:05:00Z",
        "observed_utc": "2026-09-10T18:00:00Z", "model": {},
    }


def _prop_pick(rank=1, player="Rafael Devers", market="batter_hits", line=0.5,
               side="over", price=-120, game_pk=4001, label="STRONG"):
    return {
        "kind": "prop", "rank": rank, "label": label,
        "bet": f"{player} over {line} hits", "why": ["because"],
        "player": player, "team": "BOS", "game_pk": game_pk, "event_id": "e1",
        "away_team": "BOS", "home_team": "NYY",
        "first_pitch_utc": "2026-09-10T23:05:00Z", "market": market,
        "line": line, "side": side, "probability": 0.6,
        "market_probability": 0.55, "breakeven": 0.545, "price": price,
        "book": "draftkings", "books": 8, "batting_slot": 3,
        "expected_pa": 4.2, "expected_pa_source": "season",
        "observed_utc": "2026-09-10T18:00:00Z",
    }


def _batter_row(game_pk, player_name, **stats):
    row = {"type": "batter", "game_pk": game_pk, "player_name": player_name,
          "pa": 4, "ab": 4, "h": 0, "doubles": 0, "triples": 0, "hr": 0,
          "r": 0, "rbi": 0, "bb": 0, "k": 1, "sb": 0, "total_bases": 0,
          "hits_runs_rbi": 0}
    row.update(stats)
    return row


def _linescore_row(game_pk):
    return {"type": "linescore", "game_pk": game_pk, "first_inning_scored": 0}


class DelayedSettlementCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")


class MissingThenLaterFinal(DelayedSettlementCase):
    """The acceptance criterion, at the unit level: the same stored
    selection is unresolved on run 1 and correctly settled on run 2,
    without disappearing and without being counted twice."""

    def test_a_missing_score_stays_unresolved_then_settles_on_a_later_pass(self):
        card_ledger.publish(_card(picks=[_pick(game_pk=2001, side="home",
                                               price=-150)]), path=self.path)

        row1 = card_ledger.settle("2026-09-10", {}, path=self.path)
        self.assertIsNotNone(row1, "the first pass must leave a receipt, "
                             "even with nothing gradable yet")
        self.assertEqual(card_ledger.RESULT_UNRESOLVED, row1["picks"][0]["result"])
        self.assertEqual(card_ledger.UNRESOLVED_AWAITING_RESULT,
                         row1["picks"][0]["unresolved_kind"])
        self.assertEqual(0, row1["n_staked"])
        self.assertEqual(1, row1["unresolved"])
        self.assertEqual(0, row1["voids"], "a missing score is not a void")
        self.assertTrue(card_ledger.has_unresolved_picks(row1))
        self.assertEqual(0, row1["settlement_pass"])

        # RUN 2: the game finished. THE SAME STORED SELECTION (game_pk 2001)
        # must now settle correctly, not disappear, not double count.
        row2 = card_ledger.settle(
            "2026-09-10", {2001: {"away_score": 2, "home_score": 5}},
            path=self.path)
        self.assertIsNotNone(row2)
        self.assertEqual(card_ledger.RESULT_WIN, row2["picks"][0]["result"])
        self.assertEqual(1, row2["n_staked"])
        self.assertEqual(1, row2["wins"])
        self.assertEqual(0, row2["unresolved"])
        self.assertFalse(card_ledger.has_unresolved_picks(row2))
        self.assertEqual(1, row2["settlement_pass"])
        self.assertEqual(row1["row_hash"], row2["supersedes_row_hash"])

        # settled_row returns the NEWEST row, not the first.
        self.assertEqual(row2["row_hash"],
                         card_ledger.settled_row("2026-09-10", path=self.path)["row_hash"])

        # THE READ-MODEL agrees: history() shows the settled result, not
        # the stale unresolved one, and pools it exactly once.
        day = card_ledger.history(path=self.path)["days"][0]
        self.assertEqual(1, day["wins"])
        self.assertEqual(0, day["unresolved"])
        rec = card_ledger.record(path=self.path)
        self.assertEqual(1, rec["days"], "one date, not two, even though it "
                         "took two settlement passes")
        self.assertEqual(1, rec["wins"])
        self.assertEqual(1, rec["n_staked"])

        self.assertTrue(getattr(card_ledger.verify(path=self.path), "ok", False))
        # Exactly two card_settled rows physically exist -- one per pass,
        # never collapsed, never duplicated.
        settled_rows = [r for r in card_ledger._ledger(self.path).read()
                        if r["kind"] == card_ledger.KIND_SETTLED]
        self.assertEqual(2, len(settled_rows))


class MixedCompleteIncompleteCard(DelayedSettlementCase):
    def test_one_final_one_pending_settles_the_final_and_leaves_the_rest_open(self):
        card_ledger.publish(
            _card(picks=[_pick(rank=1, game_pk=3001, side="home", price=-150),
                        _pick(rank=2, game_pk=3002, side="away", price=+120)]),
            path=self.path)

        row = card_ledger.settle(
            "2026-09-10", {3001: {"away_score": 1, "home_score": 4}},
            path=self.path)  # 3002 has no entry at all -- still in progress

        by_pk = {p["game_pk"]: p for p in row["picks"]}
        self.assertEqual(card_ledger.RESULT_WIN, by_pk[3001]["result"])
        self.assertEqual(card_ledger.RESULT_UNRESOLVED, by_pk[3002]["result"])
        self.assertEqual(1, row["n_staked"])
        self.assertEqual(1, row["wins"])
        self.assertEqual(1, row["unresolved"])
        self.assertEqual(0, row["voids"])
        # The card is not sealed -- settle_recent's own gate must see this
        # date as still eligible for a retry.
        self.assertTrue(card_ledger.has_unresolved_picks(row))

        # The read-model shows the same mix, not a card that looks finished.
        day = card_ledger.history(path=self.path)["days"][0]
        self.assertEqual(1, day["unresolved"])
        self.assertEqual(1, day["wins"])


class UnrelatedCompletedPicksUnchanged(DelayedSettlementCase):
    def test_a_later_pass_carries_terminal_picks_forward_byte_identical(self):
        card_ledger.publish(
            _card(picks=[_pick(rank=1, game_pk=5001, side="home", price=-150),
                        _pick(rank=2, game_pk=5002, side="away", price=+120),
                        _pick(rank=3, game_pk=5003, side="home", price=-110)]),
            path=self.path)

        row1 = card_ledger.settle(
            "2026-09-10",
            {5001: {"away_score": 1, "home_score": 4},   # WIN now
             5003: {"away_score": 6, "home_score": 1}},   # LOSS now
            path=self.path)   # 5002 still pending
        by_pk_1 = {p["game_pk"]: p for p in row1["picks"]}
        self.assertEqual(card_ledger.RESULT_WIN, by_pk_1[5001]["result"])
        self.assertEqual(card_ledger.RESULT_LOSS, by_pk_1[5003]["result"])
        self.assertEqual(card_ledger.RESULT_UNRESOLVED, by_pk_1[5002]["result"])

        row2 = card_ledger.settle(
            "2026-09-10",
            {5001: {"away_score": 1, "home_score": 4},
             5002: {"away_score": 2, "home_score": 9},   # NOW final
             5003: {"away_score": 6, "home_score": 1}},
            path=self.path)
        by_pk_2 = {p["game_pk"]: p for p in row2["picks"]}

        # THE UNRELATED, ALREADY-COMPLETED PICKS ARE UNCHANGED -- exact dict
        # equality, not just the same `result` string, proving they were
        # carried forward rather than silently re-graded (which could
        # re-round a profit figure, drop a field, or -- worse -- flip an
        # outcome on a re-run against a subtly different results map).
        self.assertEqual(by_pk_1[5001], by_pk_2[5001])
        self.assertEqual(by_pk_1[5003], by_pk_2[5003])
        # ...and the one that was actually pending is now resolved (5002
        # picked "away" at 2-9 -- away lost, so this settles LOSS).
        self.assertEqual(card_ledger.RESULT_LOSS, by_pk_2[5002]["result"])
        self.assertEqual(0, row2["unresolved"])


class MissingThenVerifiedVoidWithADocumentedReason(DelayedSettlementCase):
    """A prop pick whose player has no box row: UNRESOLVED while the box is
    simply not captured yet, and only becomes a genuine, documented VOID
    once the game's box IS captured and still carries no row for him --
    verifying participation before voiding, per this task's instruction."""

    def test_no_box_yet_is_unresolved_captured_box_without_the_player_is_void(self):
        card_ledger.publish(
            _card(picks=[_pick(game_pk=9999)],
                 prop_picks=[_prop_pick(player="Rafael Devers", game_pk=4001)]),
            path=self.path)

        # RUN 1: nothing captured for this game at all yet.
        row1 = card_ledger.settle(
            "2026-09-10", {9999: {"away_score": 1, "home_score": 2}},
            path=self.path, prop_box_rows=[])
        prop1 = row1["prop_picks"][0]
        self.assertEqual(card_ledger.RESULT_UNRESOLVED, prop1["result"])
        self.assertEqual(card_ledger.UNRESOLVED_AWAITING_RESULT,
                         prop1["unresolved_kind"])

        # RUN 2: the game's box IS captured now (a linescore row proves the
        # box for game_pk 4001 was ingested -- see _box_captured_game_pks),
        # and Devers still has no batter row in it -- he did not play.
        row2 = card_ledger.settle(
            "2026-09-10", {9999: {"away_score": 1, "home_score": 2}},
            path=self.path,
            prop_box_rows=[_linescore_row(4001),
                          _batter_row(4001, "Someone Else")])
        prop2 = row2["prop_picks"][0]
        self.assertEqual(card_ledger.RESULT_VOID, prop2["result"])
        self.assertIn("no recorded plate appearance", prop2["reason"])
        self.assertEqual(1, row2["prop_voids"])
        self.assertEqual(0, row2["prop_unresolved"])

    def test_a_captured_box_with_the_player_in_it_grades_normally(self):
        """Confirms the participation check does not fire when the player
        actually IS in the box -- the void path is reached only by his
        absence from a captured box, never by the box merely existing."""
        card_ledger.publish(
            _card(picks=[_pick(game_pk=9998)],
                 prop_picks=[_prop_pick(player="Rafael Devers", game_pk=4002,
                                        line=0.5, side="over")]),
            path=self.path)
        row = card_ledger.settle(
            "2026-09-10", {9998: {"away_score": 1, "home_score": 2}},
            path=self.path,
            prop_box_rows=[_batter_row(4002, "Rafael Devers", h=2)])
        self.assertEqual(card_ledger.RESULT_WIN, row["prop_picks"][0]["result"])


class DuplicateRetryDoesNotDoubleCount(DelayedSettlementCase):
    def test_settling_an_already_fully_resolved_date_again_is_a_true_no_op(self):
        card_ledger.publish(_card(picks=[_pick(game_pk=1001)]), path=self.path)
        results = {1001: {"away_score": 1, "home_score": 4}}

        row1 = card_ledger.settle("2026-09-10", results, path=self.path)
        self.assertIsNotNone(row1)
        row2 = card_ledger.settle("2026-09-10", results, path=self.path)
        self.assertIsNone(row2, "nothing changed -- must be a true no-op")

        settled_rows = [r for r in card_ledger._ledger(self.path).read()
                        if r["kind"] == card_ledger.KIND_SETTLED]
        self.assertEqual(1, len(settled_rows))
        rec = card_ledger.record(path=self.path)
        self.assertEqual(1, rec["n_staked"], "a retry must not double-count "
                         "an already-settled selection")
        self.assertEqual(1, rec["wins"])


class InterruptedReplayedWrite(DelayedSettlementCase):
    """A caller that cannot tell whether an earlier settle() call actually
    committed (a crash, a timeout, a retry after a network blip) must be
    able to blindly call settle() again with the SAME inputs and get a safe
    no-op -- never a duplicate row, never a double-counted pick, never a
    broken chain."""

    def test_replaying_a_partial_pass_is_safe_and_the_chain_still_verifies(self):
        card_ledger.publish(
            _card(picks=[_pick(rank=1, game_pk=6001, side="home", price=-150),
                        _pick(rank=2, game_pk=6002, side="away", price=+130)]),
            path=self.path)

        partial_results = {6001: {"away_score": 1, "home_score": 4}}
        row1 = card_ledger.settle("2026-09-10", partial_results, path=self.path)
        self.assertIsNotNone(row1)

        # REPLAY: the caller retries with the IDENTICAL partial results,
        # not knowing pass 1 already committed.
        replay = card_ledger.settle("2026-09-10", partial_results, path=self.path)
        self.assertIsNone(replay, "a blind replay of an unchanged pass must "
                          "not append a second row")

        # A genuinely later pass, with the second game now final, still
        # completes the date correctly after the replay.
        full_results = {6001: {"away_score": 1, "home_score": 4},
                        6002: {"away_score": 5, "home_score": 2}}
        row2 = card_ledger.settle("2026-09-10", full_results, path=self.path)
        self.assertIsNotNone(row2)
        self.assertFalse(card_ledger.has_unresolved_picks(row2))

        settled_rows = [r for r in card_ledger._ledger(self.path).read()
                        if r["kind"] == card_ledger.KIND_SETTLED]
        self.assertEqual(2, len(settled_rows), "the no-op replay must not "
                         "have appended a row")
        self.assertTrue(getattr(card_ledger.verify(path=self.path), "ok", False))

        rec = card_ledger.record(path=self.path)
        self.assertEqual(2, rec["n_staked"])
        self.assertEqual(2, rec["wins"])

    def test_settle_recent_survives_a_replayed_pass_within_the_window(self):
        """The same story through settle_recent() -- the daily loop's real
        entry point -- rather than settle() directly."""
        card_ledger.publish(
            _card("2026-09-17", picks=[_pick(rank=1, game_pk=7001),
                                       _pick(rank=2, game_pk=7002)]),
            now="2026-09-17T23:00:00Z", path=self.path, sport="nfl")

        # PASS 1: only 7001's result is in -- enough for _settle_one_date's
        # own pre-check to let settle() run at all (see _pick_lookup_keys),
        # which then resolves 7001 and leaves 7002 UNRESOLVED.
        fetch_partial = lambda d: {"7001": {"home_score": 20, "away_score": 10}}
        totals1 = card_ledger.settle_recent(
            sport="nfl", fetch_results=fetch_partial, path=self.path,
            today="2026-09-18")
        self.assertEqual(1, totals1["settled"])
        row1 = card_ledger.settled_row("2026-09-17", path=self.path, sport="nfl")
        self.assertIsNotNone(row1)
        self.assertTrue(card_ledger.has_unresolved_picks(row1),
                        "7002 has no result yet -- this date is not done")

        # REPLAY the exact same partial pass again, as a caller unsure
        # whether pass 1 actually committed would.
        totals_replay = card_ledger.settle_recent(
            sport="nfl", fetch_results=fetch_partial, path=self.path,
            today="2026-09-18")
        self.assertEqual(0, totals_replay["settled"])
        self.assertEqual(card_ledger.REASON_NO_NEW_PROGRESS,
                         totals_replay["misses"][0]["reason"])
        settled_rows = [r for r in card_ledger._ledger(self.path).read()
                        if r["kind"] == card_ledger.KIND_SETTLED
                        and r["date"] == "2026-09-17"]
        self.assertEqual(1, len(settled_rows), "the replayed partial pass "
                         "must not append a second row")

        # A later pass with 7002's result too completes the date.
        totals2 = card_ledger.settle_recent(
            sport="nfl",
            fetch_results=lambda d: {"7001": {"home_score": 20, "away_score": 10},
                                     "7002": {"home_score": 14, "away_score": 17}},
            path=self.path, today="2026-09-19")
        self.assertEqual(1, totals2["settled"])
        row2 = card_ledger.settled_row("2026-09-17", path=self.path, sport="nfl")
        self.assertFalse(card_ledger.has_unresolved_picks(row2))


class LegacySettledRowStillReadsCorrectly(DelayedSettlementCase):
    """A row written by the PRE-FIX code (single settled row per date, a
    missing score graded a permanent VOID with the old literal reason) must
    keep reading exactly as it did -- no crash, and no silent reinterpretation
    under the new rule (this task's module docstring: identify affected
    entries and report them, never auto-regrade history under a new theory)."""

    def _seed_legacy_row(self):
        published = card_ledger.publish(
            _card(date="2026-08-01",
                 picks=[_pick(rank=1, game_pk=8001, side="home", price=-140)]),
            path=self.path)
        # Hand-built exactly as the PRE-FIX settle() would have written it --
        # no "unresolved"/"settlement_pass"/"supersedes_row_hash" keys, and
        # the OLD literal VOID reason for a missing score.
        legacy_payload = {
            "kind": card_ledger.KIND_SETTLED,
            "date": "2026-08-01",
            "settled_utc": "2026-08-02T10:00:00Z",
            "published_row_hash": published["row_hash"],
            "n_picks": 1, "n_staked": 0, "wins": 0, "losses": 0, "pushes": 0,
            "voids": 1, "profit_units": 0.0, "roi_pct": None,
            "picks": [{"rank": 1, "bet": "Take game 8001 home side",
                      "label": "STRONG", "market": "moneyline", "price": -140,
                      "game_pk": 8001, "result": card_ledger.RESULT_VOID,
                      "profit_units": 0.0,
                      "reason": "no final score stored for this game"}],
            "prop_picks": [], "n_prop_picks": 0, "n_prop_staked": 0,
            "prop_wins": 0, "prop_losses": 0, "prop_pushes": 0,
            "prop_voids": 0, "prop_profit_units": 0.0, "prop_roi_pct": None,
            "total_picks": [], "n_total_picks": 0, "n_total_staked": 0,
            "total_wins": 0, "total_losses": 0, "total_pushes": 0,
            "total_voids": 0, "total_profit_units": 0.0, "total_roi_pct": None,
        }
        return card_ledger._ledger(self.path).append(legacy_payload)

    def test_settled_row_and_has_unresolved_picks_accept_the_old_shape(self):
        self._seed_legacy_row()
        row = card_ledger.settled_row("2026-08-01", path=self.path)
        self.assertIsNotNone(row)
        self.assertEqual(card_ledger.RESULT_VOID, row["picks"][0]["result"])
        self.assertEqual("no final score stored for this game",
                         row["picks"][0]["reason"])
        # A legacy VOID is a real terminal state, not UNRESOLVED -- it must
        # not be treated as still-open just because it predates this task.
        self.assertFalse(card_ledger.has_unresolved_picks(row))

    def test_settle_does_not_touch_a_legacy_fully_settled_date(self):
        """No `unresolved` key at all on the legacy row -- has_unresolved_
        picks must not crash on the missing field, and settle() must treat
        this date as done (nothing to carry forward, nothing to re-grade),
        exactly as it would a new-shape fully-resolved row."""
        self._seed_legacy_row()
        again = card_ledger.settle(
            "2026-08-01", {8001: {"away_score": 1, "home_score": 4}},
            path=self.path)
        self.assertIsNone(again, "a legacy VOID is terminal; settle() must "
                          "not re-grade it even though a score exists now")

    def test_history_and_record_read_the_legacy_row_without_crashing(self):
        self._seed_legacy_row()
        day = card_ledger.history(path=self.path)["days"][0]
        self.assertEqual(1, day["voids"])
        self.assertEqual(0, day["unresolved"])
        self.assertEqual("no final score stored for this game",
                         day["picks"][0]["reason"])
        rec = card_ledger.record(path=self.path)
        self.assertEqual(1, rec["days"])
        self.assertEqual(1, rec["voids"])
        self.assertEqual(0, rec["n_staked"])


class ACorrectedResultCountsExactlyOnce(DelayedSettlementCase):
    def test_correcting_a_wrong_terminal_result_is_reflected_once_never_edits_the_row(self):
        card_ledger.publish(
            _card(picks=[_pick(rank=1, game_pk=1001, side="home", price=-150),
                        _pick(rank=2, game_pk=1002, side="home", price=-120)]),
            path=self.path)
        raw_before = card_ledger.settle(
            "2026-09-10",
            {1001: {"away_score": 1, "home_score": 4},   # WIN
             1002: {"away_score": 1, "home_score": 4}},   # WIN
            path=self.path)
        self.assertEqual(2, raw_before["wins"])
        self.assertEqual(0, raw_before["losses"])

        # Suppose 1002's score is later revised by the provider -- the home
        # team actually lost. correct_pick asserts the fixed verdict with a
        # mandatory reason and source; it never edits the settled row.
        card_ledger.correct_pick(
            "2026-09-10", (str(1002), "moneyline", None), scope="picks",
            result={"result": card_ledger.RESULT_LOSS, "profit_units": -1.0,
                   "reason": "corrected: away team actually won",
                   "away_score": 5, "home_score": 4},
            correction_reason="provider revised the boxscore after review",
            source="test-fixture: simulated provider correction",
            path=self.path)

        # THE ORIGINAL ROW IS UNTOUCHED. Reading it raw still shows the
        # first (now-known-wrong) WIN, and the chain still verifies -- a
        # correction is an appended event, never a rewrite.
        raw_after = card_ledger.settled_row("2026-09-10", path=self.path)
        self.assertEqual(raw_before, raw_after)
        self.assertTrue(getattr(card_ledger.verify(path=self.path), "ok", False))

        # THE EFFECTIVE VIEW reflects the correction exactly once.
        effective = card_ledger.effective_settled_row("2026-09-10", path=self.path)
        self.assertEqual(1, effective["wins"])
        self.assertEqual(1, effective["losses"])
        self.assertTrue(effective["corrected"])
        self.assertEqual(1, effective["correction_count"])

        # THE READ-MODEL (history/record) folds it in too, and counts it
        # exactly once even when queried repeatedly.
        for _ in range(2):
            day = card_ledger.history(path=self.path)["days"][0]
            self.assertEqual(1, day["wins"])
            self.assertEqual(1, day["losses"])
            self.assertTrue(day["corrected"])
            corrected_pick = {p["bet"]: p for p in day["picks"]}[
                "Take game 1002 home side"]
            self.assertEqual(card_ledger.RESULT_LOSS, corrected_pick["result"])
            self.assertTrue(corrected_pick["corrected"])

            rec = card_ledger.record(path=self.path)
            self.assertEqual(1, rec["wins"])
            self.assertEqual(1, rec["losses"])
            self.assertEqual(2, rec["n_staked"], "still two staked picks -- "
                             "the correction changed WHICH one won, not how "
                             "many were staked")

    def test_correct_pick_refuses_an_undocumented_correction(self):
        card_ledger.publish(_card(picks=[_pick(game_pk=1001)]), path=self.path)
        card_ledger.settle(
            "2026-09-10", {1001: {"away_score": 1, "home_score": 4}},
            path=self.path)
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.correct_pick(
                "2026-09-10", (str(1001), "moneyline", None), scope="picks",
                result={"result": card_ledger.RESULT_LOSS},
                correction_reason="", source="somewhere", path=self.path)
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.correct_pick(
                "2026-09-10", (str(1001), "moneyline", None), scope="picks",
                result={"result": card_ledger.RESULT_LOSS},
                correction_reason="because", source="", path=self.path)

    def test_correct_pick_refuses_an_unknown_pick(self):
        card_ledger.publish(_card(picks=[_pick(game_pk=1001)]), path=self.path)
        card_ledger.settle(
            "2026-09-10", {1001: {"away_score": 1, "home_score": 4}},
            path=self.path)
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.correct_pick(
                "2026-09-10", (str(9999), "moneyline", None), scope="picks",
                result={"result": card_ledger.RESULT_LOSS},
                correction_reason="because", source="somewhere", path=self.path)


if __name__ == "__main__":
    unittest.main()
