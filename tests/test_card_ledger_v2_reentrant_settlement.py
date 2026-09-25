"""settle_v2 re-entrant settlement -- the V2 counterpart to
tests/test_card_ledger_delayed_settlement.py.

bb15ffa3 made grade_pick/grade_prop_pick stop turning a missing result into
a permanent VOID (they return UNRESOLVED instead), and made V1's own
`settle`/`_settle_one_date` re-entrant to match: a date with an UNRESOLVED
pick is retried on a later pass rather than sealed forever. `settle_v2` was
NOT updated then -- it still refused to run a second time the moment ANY
settled row existed, so a V2 entry missing its result at first settlement
was recorded UNRESOLVED and the date was sealed, never graded again. That
is worse than the pre-bb15ffa3 behaviour (at least a counted VOID). This
file pins the fix: `settle_v2` now mirrors V1's `settle` state machine
exactly (carry TERMINAL entries forward byte-identical, re-grade only
UNRESOLVED ones, append a fresh row only when something actually changed),
and `src/report/nfl_card.py`/`src/report/ufc_card.py`'s own settle_for_date
gates -- which call V1's `settle`, not `settle_v2` -- are fixed the same
way: FULLY settled means "nothing left UNRESOLVED", not merely "a settled
row exists".

Every test runs against a temporary ledger path -- none of them touch
evidence/cards_v2.jsonl or evidence/cards_v1.jsonl.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger as cl
from src.pipeline import ufc_results
from src.report import nfl_card as nfl_report
from src.report import ufc_card as ufc_report
from tests._card_v2_fixtures import game_entry, select_result, result_row


class V2Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")


# ---------------------------------------------------------------------------
# 1. unresolved on pass 1 -> verified final on pass 2 -> counted exactly once
# ---------------------------------------------------------------------------

class UnresolvedThenResolvedCountsOnce(V2Case):
    def test_a_missing_result_stays_unresolved_then_settles_on_a_later_pass(self):
        pick = game_entry(game_pk=201, price=-150)
        cl.publish_v2(select_result(picks=[pick]), now="2026-09-20T10:00:00Z",
                     path=self.path)

        row1 = cl.settle_v2("2026-09-20", {}, path=self.path)
        self.assertIsNotNone(row1, "the first pass must leave a receipt, "
                             "even with nothing gradable yet")
        self.assertEqual(cl.RESULT_UNRESOLVED, row1["graded"][0]["result"])
        self.assertEqual(0, row1["n_staked"])
        self.assertEqual(1, row1["unresolved"])
        self.assertEqual(0, row1["voids"], "a missing result is not a void")
        self.assertTrue(cl._v2_has_unresolved(row1))
        self.assertEqual(0, row1["settlement_pass"])

        # RUN 2: the game finished. THE SAME STORED ENTRY (game_pk 201) must
        # now settle correctly -- not disappear, not double count.
        row2 = cl.settle_v2("2026-09-20", {201: result_row(1, 5)}, path=self.path)
        self.assertIsNotNone(row2)
        self.assertEqual(cl.RESULT_WIN, row2["graded"][0]["result"])
        self.assertEqual(1, row2["n_staked"])
        self.assertEqual(1, row2["wins"])
        self.assertEqual(0, row2["unresolved"])
        self.assertFalse(cl._v2_has_unresolved(row2))
        self.assertEqual(1, row2["settlement_pass"])
        self.assertEqual(row1["row_hash"], row2["supersedes_row_hash"])

        # settled_row returns the NEWEST row, not the first.
        self.assertEqual(row2["row_hash"],
                         cl.settled_row("2026-09-20", path=self.path)["row_hash"])

        # THE READ-MODEL agrees and counts this exactly once across the two
        # settlement passes it actually took.
        rec = cl.record_v2(path=self.path)
        self.assertEqual(1, rec["main"]["n_staked"])
        self.assertEqual(1, rec["main"]["wins"])
        self.assertEqual(1, rec["main"]["days"])

        self.assertTrue(getattr(cl.verify(path=self.path), "ok", False))
        settled_rows = [r for r in cl._ledger(self.path).read()
                        if r["kind"] == cl.KIND_SETTLED]
        self.assertEqual(2, len(settled_rows), "one row per pass, never "
                         "collapsed, never duplicated")


# ---------------------------------------------------------------------------
# 2. mixed card: terminal entries byte-identical across passes; only the
#    unresolved one changes
# ---------------------------------------------------------------------------

class MixedCardTerminalEntriesUnchanged(V2Case):
    def test_a_later_pass_carries_terminal_entries_forward_byte_identical(self):
        win_pick = game_entry(game_pk=301, price=-150)
        loss_pick = game_entry(game_pk=303, price=+120)
        pending_pick = game_entry(game_pk=302, price=-110)
        cl.publish_v2(select_result(picks=[win_pick, loss_pick, pending_pick]),
                     now="2026-09-20T10:00:00Z", path=self.path)

        row1 = cl.settle_v2(
            "2026-09-20",
            {301: result_row(1, 5),    # home wins -> WIN
             303: result_row(5, 1)},   # home loses -> LOSS
            path=self.path)   # 302 has no entry at all -- still pending
        by_pk_1 = {g["game_pk"]: g for g in row1["graded"]}
        self.assertEqual(cl.RESULT_WIN, by_pk_1[301]["result"])
        self.assertEqual(cl.RESULT_LOSS, by_pk_1[303]["result"])
        self.assertEqual(cl.RESULT_UNRESOLVED, by_pk_1[302]["result"])

        row2 = cl.settle_v2(
            "2026-09-20",
            {301: result_row(1, 5),
             302: result_row(2, 9),    # NOW final -- home wins by 7 -> WIN
             303: result_row(5, 1)},
            path=self.path)
        by_pk_2 = {g["game_pk"]: g for g in row2["graded"]}

        # THE UNRELATED, ALREADY-TERMINAL ENTRIES ARE UNCHANGED -- exact
        # dict equality, proving they were carried forward rather than
        # silently re-graded.
        self.assertEqual(by_pk_1[301], by_pk_2[301])
        self.assertEqual(by_pk_1[303], by_pk_2[303])
        # ...and the one that was actually pending is now resolved.
        self.assertEqual(cl.RESULT_WIN, by_pk_2[302]["result"])
        self.assertEqual(0, row2["unresolved"])


# ---------------------------------------------------------------------------
# 3. a third pass with nothing new appends NO row
# ---------------------------------------------------------------------------

class ThirdPassWithNothingNewAppendsNoRow(V2Case):
    def test_a_pass_that_changes_nothing_does_not_append(self):
        resolves_soon = game_entry(game_pk=501, price=-150)
        never_resolves = game_entry(game_pk=502, price=+110)
        cl.publish_v2(select_result(picks=[resolves_soon, never_resolves]),
                     now="2026-09-20T10:00:00Z", path=self.path)

        row1 = cl.settle_v2("2026-09-20", {}, path=self.path)   # pass 1: nothing final yet
        self.assertIsNotNone(row1)
        self.assertEqual(2, row1["unresolved"])

        row2 = cl.settle_v2("2026-09-20", {501: result_row(1, 5)}, path=self.path)
        self.assertIsNotNone(row2, "501 just resolved -- this pass must append")
        self.assertEqual(1, row2["unresolved"])

        # PASS 3: the exact same partial results as pass 2 -- 502 is still
        # nowhere in the results map. Nothing changed, so nothing appends.
        row3 = cl.settle_v2("2026-09-20", {501: result_row(1, 5)}, path=self.path)
        self.assertIsNone(row3, "no new progress must not append a row")

        settled_rows = [r for r in cl._ledger(self.path).read()
                        if r["kind"] == cl.KIND_SETTLED]
        self.assertEqual(2, len(settled_rows), "pass 3 must not have "
                         "appended a third row")


# ---------------------------------------------------------------------------
# 4. a fully resolved date re-settled is a true no-op
# ---------------------------------------------------------------------------

class FullyResolvedDateReSettledIsNoOp(V2Case):
    def test_settling_an_already_fully_resolved_date_again_is_a_true_no_op(self):
        pick = game_entry(game_pk=601, price=-150)
        cl.publish_v2(select_result(picks=[pick]), now="2026-09-20T10:00:00Z",
                     path=self.path)
        results = {601: result_row(1, 5)}

        row1 = cl.settle_v2("2026-09-20", results, path=self.path)
        self.assertIsNotNone(row1)
        self.assertFalse(cl._v2_has_unresolved(row1))

        row2 = cl.settle_v2("2026-09-20", results, path=self.path)
        self.assertIsNone(row2, "nothing left unresolved -- must be a true no-op")

        settled_rows = [r for r in cl._ledger(self.path).read()
                        if r["kind"] == cl.KIND_SETTLED]
        self.assertEqual(1, len(settled_rows))
        rec = cl.record_v2(path=self.path)
        self.assertEqual(1, rec["main"]["n_staked"])
        self.assertEqual(1, rec["main"]["wins"])


# ---------------------------------------------------------------------------
# 5. a replayed/interrupted pass leaves the hash chain verifying
# ---------------------------------------------------------------------------

class ReplayedPassLeavesHashChainVerifying(V2Case):
    def test_replaying_a_partial_pass_is_safe_and_the_chain_still_verifies(self):
        first = game_entry(game_pk=701, price=-150)
        second = game_entry(game_pk=702, price=+130)
        cl.publish_v2(select_result(picks=[first, second]),
                     now="2026-09-20T10:00:00Z", path=self.path)

        partial_results = {701: result_row(1, 5)}
        row1 = cl.settle_v2("2026-09-20", partial_results, path=self.path)
        self.assertIsNotNone(row1)

        # REPLAY: the caller retries with the IDENTICAL partial results, not
        # knowing pass 1 already committed.
        replay = cl.settle_v2("2026-09-20", partial_results, path=self.path)
        self.assertIsNone(replay, "a blind replay of an unchanged pass must "
                          "not append a second row")

        # A genuinely later pass, with the second entry now final too,
        # still completes the date correctly after the replay.
        full_results = {701: result_row(1, 5), 702: result_row(9, 2)}
        row2 = cl.settle_v2("2026-09-20", full_results, path=self.path)
        self.assertIsNotNone(row2)
        self.assertFalse(cl._v2_has_unresolved(row2))

        settled_rows = [r for r in cl._ledger(self.path).read()
                        if r["kind"] == cl.KIND_SETTLED]
        self.assertEqual(2, len(settled_rows), "the no-op replay must not "
                         "have appended a row")
        self.assertTrue(getattr(cl.verify(path=self.path), "ok", False))

        # THE NEWEST ROW alone carries the true final count -- settle_v2's
        # own per-pass tally, not a naive sum across every physical settled
        # row (record_v2/history_v2 pool every KIND_SETTLED row for a date
        # without folding to the newest one first, unlike V1's record()/
        # history(); see this task's report -- a real, separately-scoped
        # follow-up this fix exposes but does not touch).
        newest = cl.settled_row("2026-09-20", path=self.path)
        self.assertEqual(2, newest["n_staked"])
        self.assertEqual(row2["row_hash"], newest["row_hash"])


# ---------------------------------------------------------------------------
# 6. withdrawn entries follow the same rules
# ---------------------------------------------------------------------------

class WithdrawnEntriesFollowTheSameRules(V2Case):
    def test_a_withdrawn_entry_stays_unresolved_then_settles_and_counts_once(self):
        pick = game_entry(game_pk=801, price=-140, observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(picks=[pick]), now="2026-09-20T10:00:00Z",
                     path=self.path)
        failing = game_entry(game_pk=801, price=-140, failed_gates=["G7_VALUE"],
                             observed_utc="2026-09-20T11:00:00Z")
        published = cl.publish_v2(select_result(picks=[failing]),
                                  now="2026-09-20T11:00:00Z", path=self.path)
        self.assertEqual(1, len(published["withdrawn"]))

        row1 = cl.settle_v2("2026-09-20", {}, path=self.path)
        withdrawn1 = [g for g in row1["graded"] if g.get("withdrawn")]
        self.assertEqual(1, len(withdrawn1))
        self.assertEqual(cl.RESULT_UNRESOLVED, withdrawn1[0]["result"])
        self.assertTrue(cl._v2_has_unresolved(row1))

        row2 = cl.settle_v2("2026-09-20", {801: result_row(1, 5)}, path=self.path)
        withdrawn2 = [g for g in row2["graded"] if g.get("withdrawn")]
        self.assertEqual(1, len(withdrawn2))
        self.assertEqual(cl.RESULT_WIN, withdrawn2[0]["result"])
        self.assertEqual(-140, withdrawn2[0]["price"])
        self.assertFalse(cl._v2_has_unresolved(row2))

        # Graded and counted EXACTLY ONCE on the newest row -- settle_v2
        # tallies withdrawn entries into the row the same way it always
        # has (a withdrawn pick is still graded, just flagged -- see the
        # module docstring), and the re-entrant carry-forward must not
        # inflate that count across the two passes it took to resolve.
        self.assertEqual(1, row2["n_staked"])
        self.assertEqual(1, row2["wins"])
        self.assertEqual(0, row2["losses"])

        settled_rows = [r for r in cl._ledger(self.path).read()
                        if r["kind"] == cl.KIND_SETTLED]
        self.assertEqual(2, len(settled_rows))


# ---------------------------------------------------------------------------
# 7. NFL and UFC wrappers re-enter for an unresolved date and no-op for a
#    fully resolved one
# ---------------------------------------------------------------------------

def _v1_pick(rank=1, market="moneyline", side="home", price=-150, line=None,
            game_pk=9001, label="STRONG"):
    """Mirrors tests/test_card_ledger_delayed_settlement.py's own `_pick` --
    duplicated locally rather than imported, matching that file's own stated
    convention (module docstring) of keeping fixture helpers private to the
    file that needs them."""
    return {
        "rank": rank, "label": label, "bet": f"Take game {game_pk} home side",
        "why": ["because"], "market": market, "line": line, "side": side,
        "team": "NYJ", "team_name": "Jets", "opponent_name": "Bills",
        "price": price, "book": "draftkings", "books": 8,
        "confidence": 0.6, "market_probability": 0.6, "model_probability": 0.6,
        "game_id": f"nfl-{game_pk}", "game_pk": game_pk, "event_id": "e1",
        "away_team": "Bills", "home_team": "Jets",
        "first_pitch_utc": "2026-09-20T23:05:00Z",
        "observed_utc": "2026-09-20T18:00:00Z", "model": {},
    }


def _v1_card(date="2026-09-20", picks=None):
    return {"date": date, "picks": picks if picks is not None else [_v1_pick()],
            "prop_picks": [], "total_picks": []}


class NflWrapperReenters(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_nfl.jsonl")

    def test_reenters_when_unresolved_and_noops_once_fully_resolved(self):
        cl.publish(_v1_card(picks=[_v1_pick(game_pk=9001)]),
                  now="2026-09-20T18:00:00Z", path=self.path, sport="nfl")

        row1 = nfl_report.settle_for_date("2026-09-20", results={}, path=self.path)
        self.assertIsNotNone(row1)
        self.assertEqual(cl.RESULT_UNRESOLVED, row1["picks"][0]["result"])

        # A wrapper-level retry while still unresolved must re-enter --
        # this is the exact gate this task fixes; before the fix, the mere
        # presence of row1 blocked every later call forever.
        row2 = nfl_report.settle_for_date(
            "2026-09-20", results={"9001": {"home_score": 20, "away_score": 10}},
            path=self.path)
        self.assertIsNotNone(row2)
        self.assertEqual(cl.RESULT_WIN, row2["picks"][0]["result"])
        self.assertFalse(cl.has_unresolved_picks(row2))

        # Now fully settled -- a further call must be a true no-op.
        row3 = nfl_report.settle_for_date(
            "2026-09-20", results={"9001": {"home_score": 20, "away_score": 10}},
            path=self.path)
        self.assertIsNone(row3)


class UfcWrapperReenters(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger_path = os.path.join(self._tmp.name, "cards_mma.jsonl")
        self.results_path = os.path.join(self._tmp.name, "ufc_results.jsonl")

    def _publish(self, home="Fighter A", away="Fighter B", price=-150.0):
        card = {
            "date": "2026-09-20", "sport": "mma", "rule": ufc_report.RULE_ID,
            "picks": [{
                "game_id": "bout1", "rank": 1, "sport": "mma",
                "home_team": home, "away_team": away, "side": "home",
                "team": home, "market": "moneyline", "line": None,
                "price": price, "book": "consensus", "market_probability": 0.62,
                "model_probability": None, "label": "FAVOURITE", "bet": "test bet",
                "why": ["test"], "kickoff_utc": "2026-09-20T20:00:00Z",
                "first_pitch_utc": "2026-09-20T20:00:00Z", "experimental": True,
            }],
        }
        return cl.publish(card, now="2026-09-20T15:00:00Z", path=self.ledger_path,
                          sport="mma")

    def test_reenters_when_unresolved_and_noops_once_fully_resolved(self):
        self._publish()

        # RUN 1: no manual result entered yet -- UNRESOLVED, not VOID (see
        # grade_pick's docstring), so the date must stay open.
        row1 = ufc_report.settle_for_date(
            "2026-09-20", now=None, path=self.ledger_path,
            results_path=self.results_path)
        self.assertIsNotNone(row1)
        self.assertEqual(cl.RESULT_UNRESOLVED, row1["picks"][0]["result"])
        self.assertTrue(cl.has_unresolved_picks(row1))

        # A wrapper-level retry while still unresolved must re-enter.
        ufc_results.record_result(
            date="2026-09-20", fight="Fighter A vs Fighter B", winner="Fighter A",
            outcome=ufc_results.OUTCOME_WIN, entered_by="ops@x.com",
            path=self.results_path)
        row2 = ufc_report.settle_for_date(
            "2026-09-20", now=None, path=self.ledger_path,
            results_path=self.results_path)
        self.assertIsNotNone(row2)
        self.assertEqual(cl.RESULT_WIN, row2["picks"][0]["result"])
        self.assertFalse(cl.has_unresolved_picks(row2))

        # Now fully settled -- a further call must be a true no-op.
        row3 = ufc_report.settle_for_date(
            "2026-09-20", now=None, path=self.ledger_path,
            results_path=self.results_path)
        self.assertIsNone(row3)


# ---------------------------------------------------------------------------
# 8. a V2 row settled under the OLD (pre-fix) code is left untouched
# ---------------------------------------------------------------------------

class OldCodeSettledRowLeftUntouched(V2Case):
    """The pre-fix `settle_v2` wrote a single settled row per date with no
    `unresolved`/`settlement_pass`/`supersedes_row_hash`/`published_row_hash`
    keys at all (see the removed payload this task replaces). A date that
    old code already settled CLEANLY -- nothing UNRESOLVED on the row -- must
    still read as done and must never be rewritten under the new shape."""

    def _seed_old_shape_row(self, published_row):
        legacy_payload = {
            "kind": cl.KIND_SETTLED,
            "date": "2026-09-20",
            "settled_utc": "2026-09-21T10:00:00Z",
            "rule": published_row.get("rule"),
            "graded": [dict(published_row["all_bets"][0],
                            result=cl.RESULT_WIN, profit_units=0.7143,
                            withdrawn=False, graded_without_lock_run=False)],
            "wins": 1, "losses": 0, "pushes": 0, "voids": 0,
            "n_staked": 1, "profit_units": 0.7143,
            "graded_without_lock_run": False,
        }
        return cl._ledger(self.path).append(legacy_payload)

    def test_a_cleanly_resolved_legacy_row_is_a_true_no_op(self):
        pick = game_entry(game_pk=901, price=-140)
        published = cl.publish_v2(select_result(picks=[pick]),
                                  now="2026-09-20T10:00:00Z", path=self.path)
        legacy_row = self._seed_old_shape_row(published)

        self.assertFalse(cl._v2_has_unresolved(legacy_row))
        again = cl.settle_v2("2026-09-20", {901: result_row(1, 5)}, path=self.path)
        self.assertIsNone(again, "a cleanly-resolved legacy row must not be "
                          "re-graded under the new shape")

        raw = cl.settled_row("2026-09-20", path=self.path)
        self.assertEqual(legacy_row, raw)
        settled_rows = [r for r in cl._ledger(self.path).read()
                        if r["kind"] == cl.KIND_SETTLED]
        self.assertEqual(1, len(settled_rows))
        self.assertTrue(getattr(cl.verify(path=self.path), "ok", False))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Readers fold to the newest settled row per date (integration review,
# 2026-09-25): once settle_v2 can write two rows for one date, a reader that
# sums every physical row counts the carried-forward entries twice.
# ---------------------------------------------------------------------------

class ReadersCountASecondPassOnce(V2Case):
    def _two_pass_date(self):
        picks = [game_entry(game_pk=401, price=-150),
                 game_entry(game_pk=402, price=+120),
                 game_entry(game_pk=403, price=-110)]
        cl.publish_v2(select_result(picks=picks), now="2026-09-20T10:00:00Z",
                     path=self.path)
        cl.settle_v2("2026-09-20", {401: result_row(1, 5), 402: result_row(5, 1)},
                     path=self.path)
        cl.settle_v2("2026-09-20", {401: result_row(1, 5), 402: result_row(5, 1),
                                    403: result_row(2, 9)}, path=self.path)
        settled = [r for r in cl._ledger(self.path).read()
                   if r["kind"] == cl.KIND_SETTLED]
        self.assertEqual(2, len(settled), "precondition: two physical passes")

    def test_record_v2_counts_each_pick_once(self):
        self._two_pass_date()
        combined = cl.record_v2(path=self.path)["combined"]
        self.assertEqual(3, combined["n_staked"])
        self.assertEqual((2, 1), (combined["wins"], combined["losses"]))
        self.assertEqual(1, combined["days"])

    def test_history_v2_shows_the_date_once_with_the_newest_row(self):
        self._two_pass_date()
        hist = cl.history_v2(path=self.path, limit=None)
        self.assertEqual(1, hist["total_days"])
        self.assertEqual(3, hist["days"][0]["n_staked"])

    def test_clv_measures_each_entry_once(self):
        from src.report import card_clv
        self._two_pass_date()
        out = card_clv.measure_ledger(self.path, {})
        self.assertEqual(3, len(out))
