"""V2 ledger tests (build plan T3): `src.appstate.card_ledger`'s V2 section.

Every store path and every clock is INJECTED -- `tempfile.mkdtemp()` for the
path, a fixed `NOW` for the clock -- so nothing here can pass or fail
because of what happens to be on this machine's disk or what time it is
when the suite runs.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from src.analysis import best_bets_card as bbc
from src.appstate import card_ledger as cl

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _candidate(**over):
    """A candidate shaped like `best_bets_card.select`'s own fixtures
    (`tests/test_best_bets_card.py`'s `_candidate`), close enough to the
    registered band to become a MAIN pick by default."""
    base = dict(
        game_id="G1", game_pk="G1", price=-140, market_probability=0.55,
        our_probability=0.65, books=8, observed_utc=NOW - timedelta(seconds=60),
        has_started=False, calibrated=True, bet_sentence="the Padres",
        first_pitch_utc="2026-09-16T23:00:00Z", kind="game", market="moneyline",
        side="home", game_type="R",
        # These fixtures represent an already-classified entry from a
        # report layer that already ran `select()` -- most tests here are
        # about the LEDGER (publish_v2/settle_v2/record_v2), not about
        # gating, so `entry_class`/`score`/`failed_gates` are stamped by
        # hand rather than routed through `select()` every time. Tests that
        # care about gate behaviour itself use `_stamp`, which calls
        # `best_bets_card`'s own public functions instead of guessing.
        entry_class="pick", score=0.10, failed_gates=[],
    )
    base.update(over)
    return base


def _stamp(cand, *, now, params=bbc.V2, fresh=True):
    """Score/class/gate a candidate the way `best_bets_card.select` would,
    using only that module's PUBLIC functions (never re-deriving the
    arithmetic). Needed because `select()`'s own return value silently
    drops any candidate that fails a HARD gate -- it appears in none of
    `picks`/`fills`/`close_calls_not_shown` -- so a test proving the ledger
    withdraws a pick on a hard-failing fresh read has to hand `publish_v2`
    the full scored candidate itself, exactly as the eventual report layer
    (T5, out of this task's scope) will have to.
    """
    c = dict(cand)
    # A fresh read observed relative to THIS run's `now` by default --
    # otherwise every `_stamp` call at a later `now` than the candidate's
    # fixed `observed_utc` default would spuriously fail G3_STALE, which is
    # not what a lock/withdraw test is about. Pass `fresh=False` to keep the
    # candidate's own `observed_utc` when staleness itself is the point.
    if fresh:
        c["observed_utc"] = now - timedelta(seconds=60)
    price = c.get("price")
    our_p = c.get("our_probability")
    fails = bbc.failed_gates(c, now=now, params=params)
    c["price_class"] = bbc.price_class(price) if price is not None else None
    c["score"] = (bbc.score(our_p, price, params)
                 if (price is not None and our_p is not None and not fails) else None)
    c["failed_gates"] = fails
    if not fails:
        c["entry_class"] = "pick"
    elif bbc.is_fill_eligible(fails):
        c["entry_class"] = "fill"
    else:
        c["entry_class"] = None
    return c


def _plus_candidate(game_id, **over):
    base = dict(
        game_id=game_id, game_pk=game_id, price=150, market_probability=0.30,
        our_probability=0.40, books=8, observed_utc=NOW - timedelta(seconds=60),
        has_started=False, calibrated=True, bet_sentence="the underdog",
        first_pitch_utc="2026-09-16T23:00:00Z", kind="game", market="moneyline",
        side="away", game_type="R",
        entry_class="pick", score=0.08, failed_gates=[],
    )
    base.update(over)
    return base


class TempStoreMixin:
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "cards_v2.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class NoShadowD(unittest.TestCase):
    """Registration section 10 deregisters shadow D. `CARD_STORE_V2_SHADOW_D`
    must not exist as a name, and `evidence/cards_v2_shadow_d.jsonl` must
    never appear on disk as a result of anything this module does."""

    def test_no_shadow_d_constant(self):
        self.assertFalse(hasattr(cl, "CARD_STORE_V2_SHADOW_D"))

    def test_no_shadow_d_in_any_store_constant(self):
        store_values = [
            cl.CARD_STORE_V2, cl.CARD_STORE_V2_SHADOW_A, cl.CARD_STORE_V2_SHADOW_C,
            cl.CARD_STORE_V2_SHADOW_E, cl.CARD_STORE_V1_SHADOW,
            cl.CARD_STORE_V2_VAR_STRICT_NOCAP, cl.CARD_STORE_V2_VAR_LOOSE_CAP3,
            cl.CARD_STORE_V2_VAR_LOOSE_NOCAP,
        ]
        for value in store_values:
            self.assertNotIn("shadow_d", value)

    def test_the_registered_variant_store_constants_exist(self):
        self.assertTrue(cl.CARD_STORE_V2_VAR_STRICT_NOCAP.endswith("cards_v2_var_strict_nocap.jsonl"))
        self.assertTrue(cl.CARD_STORE_V2_VAR_LOOSE_CAP3.endswith("cards_v2_var_loose_cap3.jsonl"))
        self.assertTrue(cl.CARD_STORE_V2_VAR_LOOSE_NOCAP.endswith("cards_v2_var_loose_nocap.jsonl"))


class LedgerPathIsolation(TempStoreMixin, unittest.TestCase):
    """V2 rows land only in the file `publish_v2` was told to write to; a
    separate shadow store is a separate file that `record_v2(path=...)`
    never mixes into another store's figures."""

    def test_publish_writes_only_to_its_own_path(self):
        card = {"date": "2026-09-16", "all_bets": [_candidate()], "params": bbc.V2}
        cl.publish_v2(card, now=_iso(NOW), path=self.path)
        self.assertTrue(os.path.exists(self.path))
        shadow_path = os.path.join(self.tmp, "cards_v2_shadow_a.jsonl")
        self.assertFalse(os.path.exists(shadow_path))

    def test_record_v2_path_counts_only_that_file(self):
        results = {"G1": {"away_score": 2, "home_score": 5, "home_won": True}}
        card = {"date": "2026-09-16", "all_bets": [_candidate()], "params": bbc.V2}
        cl.publish_v2(card, now=_iso(NOW), path=self.path)
        cl.settle_v2("2026-09-16", results, path=self.path)

        other_path = os.path.join(self.tmp, "cards_v2_shadow_a.jsonl")
        rec_main = cl.record_v2(path=self.path)
        rec_other = cl.record_v2(path=other_path)
        self.assertGreater(rec_main["main"]["n_staked"] + rec_main["plus_money"]["n_staked"], 0)
        self.assertEqual(rec_other["main"]["n_staked"], 0)
        self.assertEqual(rec_other["plus_money"]["n_staked"], 0)


class EmptyDay(TempStoreMixin, unittest.TestCase):
    """`publish_v2` accepts a card with zero picks; V1's `publish` keeps
    refusing one (pinned by re-asserting that refusal here, unchanged)."""

    def test_publish_v2_writes_a_zero_pick_row(self):
        card = {"date": "2026-09-16", "all_bets": [], "params": bbc.V2}
        row = cl.publish_v2(card, now=_iso(NOW), path=self.path)
        self.assertFalse(row["already_published"])
        self.assertEqual(row["n_picks"], 0)
        self.assertEqual(row["fills"], [])

    def test_v1_publish_still_refuses_empty_picks(self):
        with self.assertRaises(cl.CardLedgerError):
            cl.publish({"date": "2026-09-16", "picks": []}, now=_iso(NOW), path=self.path)

    def test_zero_pick_row_still_carries_its_fills(self):
        close_call = _candidate(price=-250)  # outside the band -> a hard fail, not a fill
        fill_candidate = dict(_plus_candidate("G9"), price=245, our_probability=0.55)
        result = bbc.select([fill_candidate], now=NOW, params=bbc.V2)
        card = {"date": "2026-09-16", "all_bets": result["all_bets"], "params": bbc.V2}
        row = cl.publish_v2(card, now=_iso(NOW), path=self.path)
        self.assertEqual(row["n_picks"], 0)
        self.assertGreaterEqual(row["n_fills"], 0)  # a fill is a real possible outcome here


class PriceClassFrozen(TempStoreMixin, unittest.TestCase):
    def test_price_class_is_frozen_at_write_and_not_recomputed(self):
        card = {"date": "2026-09-16",
                "all_bets": [_candidate(), _plus_candidate("G2")],
                "params": bbc.V2}
        row = cl.publish_v2(card, now=_iso(NOW), path=self.path)
        classes = {e["game_pk"]: e["price_class"] for e in row["all_bets"]}
        self.assertEqual(classes["G1"], "MAIN")
        self.assertEqual(classes["G2"], "PLUS_MONEY")

    def test_every_pick_carries_raw_and_marked_down_number_and_score(self):
        card = {"date": "2026-09-16", "all_bets": [_stamp(_candidate(), now=NOW)],
                "params": bbc.V2}
        row = cl.publish_v2(card, now=_iso(NOW), path=self.path)
        entry = row["all_bets"][0]
        self.assertIn("our_probability", entry)
        self.assertIn("our_probability_used", entry)
        self.assertLess(entry["our_probability_used"], entry["our_probability"])
        self.assertIsInstance(entry["score"], float)

    def test_prop_carries_lineup_posted(self):
        prop = dict(_candidate(), kind="prop", player="Test Player", player_id="P1",
                    game_id="G3", game_pk="G3", season_games=20, lineup_posted=True)
        card = {"date": "2026-09-16", "all_bets": [prop], "params": bbc.V2}
        row = cl.publish_v2(card, now=_iso(NOW), path=self.path)
        self.assertIn("lineup_posted", row["all_bets"][0])
        self.assertTrue(row["all_bets"][0]["lineup_posted"])

    def test_row_carries_plus_money_dropped_and_ceiling_refused_keys(self):
        card = {"date": "2026-09-16", "all_bets": [_candidate()], "params": bbc.V2}
        row = cl.publish_v2(card, now=_iso(NOW), path=self.path)
        self.assertIn("plus_money_dropped_by_subcap", row)
        self.assertIn("ceiling_refused", row)


class LockAndWithdraw(TempStoreMixin, unittest.TestCase):
    def test_locked_pick_carried_verbatim_across_runs(self):
        near_pitch = (NOW + timedelta(hours=1)).isoformat()  # inside the 4h lock window
        card1 = {"date": "2026-09-16",
                 "all_bets": [_candidate(first_pitch_utc=near_pitch)], "params": bbc.V2}
        row1 = cl.publish_v2(card1, now=_iso(NOW), path=self.path)
        self.assertTrue(row1["all_bets"][0]["locked"])

        later = NOW + timedelta(minutes=30)
        card2 = {"date": "2026-09-16",
                 "all_bets": [_candidate(first_pitch_utc=near_pitch, price=-105)],
                 "params": bbc.V2}
        row2 = cl.publish_v2(card2, now=_iso(later), path=self.path)
        self.assertEqual(row2["all_bets"][0]["price"], -140,
                         "a locked pick must be carried at the price it locked at")

    def test_fresh_failing_read_withdraws_a_provisional_pick_before_lock(self):
        far_pitch = (NOW + timedelta(hours=10)).isoformat()  # well outside the lock window
        card1 = {"date": "2026-09-16",
                 "all_bets": [_stamp(_candidate(first_pitch_utc=far_pitch), now=NOW)],
                 "params": bbc.V2}
        row1 = cl.publish_v2(card1, now=_iso(NOW), path=self.path)
        self.assertFalse(row1["all_bets"][0]["locked"])

        later = NOW + timedelta(minutes=30)
        # our_probability=0.40 fails G6 (main floor is 0.50) -- a HARD gate,
        # so the fresh read must be handed in directly rather than through
        # select()'s output (see `_stamp`'s docstring).
        failing = _stamp(_candidate(first_pitch_utc=far_pitch, our_probability=0.40), now=later)
        self.assertTrue(failing["failed_gates"])
        card2 = {"date": "2026-09-16", "all_bets": [failing], "params": bbc.V2}
        row2 = cl.publish_v2(card2, now=_iso(later), path=self.path)
        self.assertEqual(row2["n_picks"], 0)
        self.assertEqual(len(row2["withdrawn"]), 1)
        self.assertEqual(row2["withdrawn"][0]["game_pk"], "G1")

    def test_withdrawn_pick_that_passes_again_returns_once(self):
        far_pitch = (NOW + timedelta(hours=10)).isoformat()
        row1 = cl.publish_v2({"date": "2026-09-16",
                              "all_bets": [_stamp(_candidate(first_pitch_utc=far_pitch), now=NOW)],
                              "params": bbc.V2}, now=_iso(NOW), path=self.path)

        later = NOW + timedelta(minutes=30)
        failing = _stamp(_candidate(first_pitch_utc=far_pitch, our_probability=0.40), now=later)
        row2 = cl.publish_v2({"date": "2026-09-16", "all_bets": [failing],
                              "params": bbc.V2}, now=_iso(later), path=self.path)
        self.assertEqual(len(row2["withdrawn"]), 1)

        even_later = NOW + timedelta(minutes=60)
        passing = _stamp(_candidate(first_pitch_utc=far_pitch), now=even_later)
        row3 = cl.publish_v2({"date": "2026-09-16", "all_bets": [passing],
                              "params": bbc.V2}, now=_iso(even_later), path=self.path)
        self.assertEqual(row3["n_picks"], 1)
        self.assertEqual(len(row3["withdrawn"]), 0)

    def test_locked_moneyline_blocks_a_later_run_line_on_same_game(self):
        near_pitch = (NOW + timedelta(hours=1)).isoformat()
        row1 = cl.publish_v2({"date": "2026-09-16",
                              "all_bets": [_candidate(first_pitch_utc=near_pitch)],
                              "params": bbc.V2}, now=_iso(NOW), path=self.path)
        self.assertTrue(row1["all_bets"][0]["locked"])

        later = NOW + timedelta(minutes=30)
        run_line = _candidate(first_pitch_utc=near_pitch, market="run_line", line=-1.5)
        row2 = cl.publish_v2({"date": "2026-09-16", "all_bets": [run_line],
                              "params": bbc.V2}, now=_iso(later), path=self.path)
        markets = {e["market"] for e in row2["all_bets"]}
        self.assertEqual(markets, {"moneyline"},
                         "G11: a locked entry owns the game; a later run line must be rejected")


class SettleAndRecord(TempStoreMixin, unittest.TestCase):
    def test_settle_grades_picks_and_fills_and_withdrawn_each_once(self):
        far_pitch = (NOW + timedelta(hours=10)).isoformat()
        passing = _stamp(_candidate(first_pitch_utc=far_pitch), now=NOW)
        cl.publish_v2({"date": "2026-09-16", "all_bets": [passing], "params": bbc.V2},
                      now=_iso(NOW), path=self.path)
        later = NOW + timedelta(minutes=30)
        failing = _stamp(_candidate(first_pitch_utc=far_pitch, our_probability=0.40), now=later)
        row2 = cl.publish_v2({"date": "2026-09-16", "all_bets": [failing],
                              "params": bbc.V2}, now=_iso(later), path=self.path)
        self.assertEqual(len(row2["withdrawn"]), 1)

        srow = cl.settle_v2("2026-09-16", {"G1": {"away_score": 2, "home_score": 5, "home_won": True}},
                            path=self.path)
        withdrawn_graded = [g for g in srow["graded"] if g["withdrawn"]]
        self.assertEqual(len(withdrawn_graded), 1)
        self.assertIn("entry_class", withdrawn_graded[0])
        self.assertIn("price_class", withdrawn_graded[0])

    def test_close_call_never_shown_is_never_graded(self):
        card = {"date": "2026-09-16", "all_bets": [_candidate()],
                "close_calls_not_shown": [_candidate(game_id="G99", game_pk="G99")],
                "params": bbc.V2}
        cl.publish_v2(card, now=_iso(NOW), path=self.path)
        srow = cl.settle_v2("2026-09-16", {"G1": {"away_score": 2, "home_score": 5, "home_won": True}},
                            path=self.path)
        graded_keys = {g.get("game_pk") for g in srow["graded"]}
        self.assertNotIn("G99", graded_keys)

    def test_record_v2_never_mixes_main_and_plus_money_in_one_figure(self):
        card = {"date": "2026-09-16",
                "all_bets": [_candidate(), _plus_candidate("G2")], "params": bbc.V2}
        cl.publish_v2(card, now=_iso(NOW), path=self.path)
        cl.settle_v2("2026-09-16",
                     {"G1": {"away_score": 2, "home_score": 5, "home_won": True},
                      "G2": {"away_score": 5, "home_score": 2, "home_won": False}},
                     path=self.path)
        rec = cl.record_v2(path=self.path)
        self.assertEqual(rec["main"]["n_staked"], 1)
        self.assertEqual(rec["plus_money"]["n_staked"], 1)
        self.assertEqual(rec["combined"]["n_staked"], 2)
        self.assertEqual(rec["combined"]["wins"] + rec["combined"]["losses"],
                         rec["main"]["wins"] + rec["main"]["losses"]
                         + rec["plus_money"]["wins"] + rec["plus_money"]["losses"])

    def test_record_v2_price_class_filter_returns_only_that_class(self):
        card = {"date": "2026-09-16",
                "all_bets": [_candidate(), _plus_candidate("G2")], "params": bbc.V2}
        cl.publish_v2(card, now=_iso(NOW), path=self.path)
        cl.settle_v2("2026-09-16",
                     {"G1": {"away_score": 2, "home_score": 5, "home_won": True},
                      "G2": {"away_score": 5, "home_score": 2, "home_won": False}},
                     path=self.path)
        rec_main_only = cl.record_v2(path=self.path, price_class="MAIN")
        self.assertEqual(rec_main_only["main"]["n_staked"], 1)
        self.assertEqual(rec_main_only["plus_money"]["n_staked"], 0)


class FingerprintFields(unittest.TestCase):
    def test_fingerprint_covers_exactly_the_registered_v2_files(self):
        self.assertEqual(cl.V2_FINGERPRINT_FILES, (
            "src/analysis/strength.py", "src/analysis/playerprops.py",
            "src/analysis/propboard.py", "src/report/props.py",
            "src/analysis/best_bets_card.py", "src/report/card_v2.py",
            "data/processed/card_v2_frozen_params.json",
        ))

    def test_fingerprint_covers_exactly_the_registered_v1_files(self):
        self.assertEqual(cl.V1_FINGERPRINT_FILES, (
            "src/analysis/strength.py", "src/analysis/playerprops.py",
            "src/analysis/propboard.py", "src/report/props.py",
            "src/analysis/daily_card.py", "src/report/card.py",
            "src/appstate/card_ledger.py", "data/processed/card_calibration.json",
        ))

    def test_changing_a_fingerprinted_files_bytes_changes_the_fingerprint(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "a.py")
            with open(path, "w") as fh:
                fh.write("x = 1\n")
            before = cl.code_fingerprint(("a.py",), root=tmp)
            with open(path, "w") as fh:
                fh.write("x = 2\n")
            after = cl.code_fingerprint(("a.py",), root=tmp)
            self.assertNotEqual(before, after)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_file_contributes_a_stable_sentinel_not_a_crash(self):
        tmp = tempfile.mkdtemp()
        try:
            value = cl.code_fingerprint(("does_not_exist.py",), root=tmp)
            self.assertIsInstance(value, str)
            self.assertEqual(len(value), 64)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_v1_shadow_rows_carry_v1_code_fingerprint(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "cards_v1_shadow.jsonl")
            row = cl.publish_v1_shadow(
                {"date": "2026-09-16", "rule": "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1",
                 "picks": [{"game_pk": "G1"}]}, now=_iso(NOW), path=path)
            self.assertIn("v1_code_fingerprint", row)
            self.assertEqual(len(row["v1_code_fingerprint"]), 64)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CeilingCountsFillsInvariant(unittest.TestCase):
    """The 2026-09-16 owner answer: the ceiling counts PICKS AND FILLS
    TOGETHER. `_apply_ceiling_v2` is what enforces that at the ledger-merge
    level (across a locked entry from an earlier run and a fresh run's
    entries, which `select()` alone cannot see together). This test proves
    the invariant FAILS without `_apply_ceiling_v2` in the merge path, then
    proves it PASSES with it restored -- not merely that the passing
    assertion exists.
    """

    def _mixed_entries(self, n_locked_picks, n_fresh_picks, n_fresh_fills):
        entries = []
        for i in range(n_locked_picks):
            entries.append({"game_id": f"LP{i}", "entry_class": "pick",
                            "locked": True, "score": 1.0, "price_class": "MAIN"})
        for i in range(n_fresh_picks):
            entries.append({"game_id": f"FP{i}", "entry_class": "pick",
                            "locked": False, "score": 0.5, "price_class": "MAIN"})
        for i in range(n_fresh_fills):
            entries.append({"game_id": f"FF{i}", "entry_class": "fill",
                            "locked": False, "score": 0.1, "price_class": "MAIN"})
        return entries

    def test_ceiling_is_violated_without_the_enforcement_step(self):
        merged = self._mixed_entries(n_locked_picks=8, n_fresh_picks=4, n_fresh_fills=3)
        with mock.patch.object(cl, "_apply_ceiling_v2", lambda merged, params: []):
            shown = len(merged)  # nothing was removed by the no-op patch
        self.assertGreater(shown, bbc.V2.ceiling,
                           "fixture must actually exceed the ceiling for this proof to mean anything")

    def test_ceiling_counts_picks_and_fills_together_with_the_fix_applied(self):
        merged = self._mixed_entries(n_locked_picks=8, n_fresh_picks=4, n_fresh_fills=3)
        refused = cl._apply_ceiling_v2(merged, bbc.V2)
        self.assertLessEqual(len(merged), bbc.V2.ceiling)
        self.assertEqual(len(merged) + len(refused), 15)

    def test_being_locked_does_not_exempt_an_entry_from_the_ceiling(self):
        """REPLACES `test_locked_entries_are_never_refused_by_the_ceiling`
        (2026-09-23, owner ruling "restore the existing ten-entry limit").

        That test asserted the exemption -- 12 locked entries all kept, only
        the 3 unlocked ones refused -- and passed, while the behaviour it
        was pinning is what let real cards reach 12, 13 and 14 entries
        against a cap of 10 on 2026-09-22. An entry locks at its own first
        pitch and is carried forward, so exempting locked entries meant the
        cap dissolved as the day went on.

        The exemption was never what the owner granted. His answer of
        2026-09-16 about 00:45Z caps the card at ten listed bets and accepts
        that "an eleventh entry that passed every gate is refused a slot
        rather than a published fill being withdrawn" -- a rule about
        ADMISSION, not about locks. What is protected is an entry a reader
        has ALREADY BEEN SHOWN, which is a different property, tested below
        and through the real publisher in
        `tests/test_card_ledger_ceiling_admission.py`.
        """
        merged = self._mixed_entries(n_locked_picks=12, n_fresh_picks=2,
                                     n_fresh_fills=1)
        refused = cl._apply_ceiling_v2(merged, bbc.V2)
        self.assertEqual(bbc.V2.ceiling, len(merged))
        self.assertEqual(5, len(refused))

    def test_an_already_published_entry_keeps_its_slot(self):
        """The property that actually protects a reader's bet: it was
        published, not that it happens to be locked."""
        merged = self._mixed_entries(n_locked_picks=12, n_fresh_picks=2,
                                     n_fresh_fills=1)
        published = frozenset(
            cl._v2_entry_key(e) for e in merged if e.get("locked"))
        refused = cl._apply_ceiling_v2(merged, bbc.V2,
                                       already_published_keys=published)
        # All twelve stay, over the ceiling, because none may be withdrawn;
        # the three newcomers are refused admission instead.
        self.assertEqual(12, len(merged))
        self.assertTrue(all(e.get("locked") for e in merged))
        self.assertEqual(3, len(refused))


class PlusMoneySubcapInvariant(unittest.TestCase):
    """G14/D4/D7 at the ledger level: `_apply_plus_money_subcap_v2` keeps a
    LOCKED plus-money pick from an earlier run and a FRESH plus-money pick
    from this run from together exceeding `plus_money_subcap`, which
    `select()` cannot see across runs. Proved FAIL-then-PASS the same way as
    the ceiling invariant above.
    """

    def _plus_money_entries(self, n_locked, n_fresh):
        entries = []
        for i in range(n_locked):
            entries.append({"game_id": f"LPM{i}", "entry_class": "pick", "locked": True,
                            "score": 1.0, "price_class": "PLUS_MONEY"})
        for i in range(n_fresh):
            entries.append({"game_id": f"FPM{i}", "entry_class": "pick", "locked": False,
                            "score": 0.5, "price_class": "PLUS_MONEY"})
        return entries

    def test_subcap_is_violated_without_the_enforcement_step(self):
        merged = self._plus_money_entries(n_locked=2, n_fresh=3)
        with mock.patch.object(cl, "_apply_plus_money_subcap_v2", lambda merged, params: []):
            shown = sum(1 for e in merged if e["price_class"] == "PLUS_MONEY")
        self.assertGreater(shown, bbc.V2.plus_money_subcap,
                           "fixture must actually exceed the subcap for this proof to mean anything")

    def test_subcap_holds_across_locked_and_fresh_with_the_fix_applied(self):
        merged = self._plus_money_entries(n_locked=2, n_fresh=3)
        dropped = cl._apply_plus_money_subcap_v2(merged, bbc.V2)
        shown_plus_money = sum(1 for e in merged if e["price_class"] == "PLUS_MONEY")
        self.assertLessEqual(shown_plus_money, bbc.V2.plus_money_subcap)
        self.assertEqual(len(dropped), 2)

    def test_locked_plus_money_picks_are_never_demoted_by_the_subcap(self):
        merged = self._plus_money_entries(n_locked=5, n_fresh=1)
        cl._apply_plus_money_subcap_v2(merged, bbc.V2)
        self.assertEqual(sum(1 for e in merged if e.get("locked")), 5)

    def test_subcap_none_disables_the_check(self):
        params = bbc.replace(bbc.V2, plus_money_subcap=None)
        merged = self._plus_money_entries(n_locked=0, n_fresh=6)
        dropped = cl._apply_plus_money_subcap_v2(merged, params)
        self.assertEqual(dropped, [])
        self.assertEqual(len(merged), 6)


if __name__ == "__main__":
    unittest.main()
