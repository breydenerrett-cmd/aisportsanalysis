"""The ten-entry ceiling, through the REAL publisher across successive runs.

`tests/test_ceiling_admission.py` covers the standalone helper. This file
covers what actually matters: `card_ledger.publish_v2` called repeatedly
against a real ledger file, the way the scheduler calls it through a day, so
a rule that holds in a helper but leaks in the merge path cannot pass.

Every test writes to a temp ledger. None touches `evidence/`.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.analysis import best_bets_card
from src.appstate import card_ledger, ceiling_admission


NOW = datetime(2026, 9, 23, 16, 0, 0, tzinfo=timezone.utc)
# Far enough ahead that nothing locks by first pitch unless a test says so.
LATE = "2026-09-24T02:05:00Z"


def _prop(n, *, score=1.0, cls="pick", first_pitch=LATE):
    """A prop entry, because props are what V2 has actually published."""
    return {
        "kind": "prop",
        "player_id": 1000 + n,
        "player": f"Player {n}",
        "game_id": f"G{n}-2026-09-23-1",
        "game_pk": 800000 + n,
        "bet": f"Player {n} over 0.5 hits",
        "bet_sentence": f"Player {n} over 0.5 hits",
        "market": "batter_hits",
        "line": 0.5,
        "side": "over",
        "price": -120,
        "books": 6,
        "season_games": 120,
        "our_probability": 0.62,
        "market_probability": 0.55,
        "observed_utc": NOW.isoformat(),
        "first_pitch_utc": first_pitch,
        "first_pitch": first_pitch,
        "calibrated": True,
        "has_started": False,
        "entry_class": cls,
        "score": score,
        "failed_gates": [] if cls == "pick" else ["G7_VALUE"],
    }


def _card(entries, *, date="2026-09-23"):
    return {"date": date, "all_bets": list(entries),
            "params": best_bets_card.V2}


class PublishV2CeilingAcrossRuns(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")

    def _publish(self, entries, *, now, date="2026-09-23"):
        return card_ledger.publish_v2(
            _card(entries, date=date), now=now.isoformat(), path=self.path)

    def _rows(self):
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_a_first_publish_is_capped_at_ten(self):
        row = self._publish([_prop(i, score=1.0 - i / 100.0)
                             for i in range(14)], now=NOW)
        self.assertEqual(10, len(row["all_bets"]))
        self.assertEqual(4, len(row["ceiling_refused"]))
        self.assertEqual(card_ledger.CEILING_ADMISSION_VERSION,
                         row["ceiling_admission_version"])

    def test_the_highest_scored_new_entries_are_the_ones_admitted(self):
        row = self._publish([_prop(i, score=i / 100.0) for i in range(14)],
                            now=NOW)
        admitted = {e["player_id"] for e in row["all_bets"]}
        # scores rise with i, so the top ten are i=4..13
        self.assertEqual({1000 + i for i in range(4, 14)}, admitted)

    def test_successive_runs_never_grow_the_card_past_the_ceiling(self):
        """The 2026-09-22 shape: entries accumulate run after run and lock as
        their games start. The old rule let the card reach 14."""
        moment = NOW
        for count in (3, 5, 6, 12, 13, 14):
            entries = [_prop(i, score=1.0 - i / 100.0) for i in range(count)]
            row = self._publish(entries, now=moment)
            self.assertLessEqual(
                len(row["all_bets"]), best_bets_card.V2.ceiling,
                f"run with {count} fresh entries published "
                f"{len(row['all_bets'])}")
            moment = moment + timedelta(minutes=30)
        self.assertEqual(10, len(self._rows()[-1]["all_bets"]))

    def test_a_new_entry_cannot_buy_a_slot_by_arriving_locked(self):
        """The specific bypass the owner named.

        Ten entries are already published. An eleventh arrives for a game
        that has ALREADY STARTED, so the merge locks it on sight. Under the
        old rule a locked entry was exempt from the ceiling and would have
        been admitted; admission looks at whether it was previously
        published, so it is refused a slot instead.
        """
        first = [_prop(i, score=1.0 - i / 100.0) for i in range(10)]
        self._publish(first, now=NOW)

        later = NOW + timedelta(hours=1)
        gatecrasher = _prop(99, score=5.0,
                            first_pitch=(later - timedelta(minutes=5))
                            .isoformat().replace("+00:00", "Z"))
        row = self._publish(first + [gatecrasher], now=later)

        self.assertEqual(10, len(row["all_bets"]))
        self.assertNotIn(1099, {e["player_id"] for e in row["all_bets"]})
        self.assertIn(1099, {e["player_id"] for e in row["ceiling_refused"]})

    def test_nothing_already_published_is_ever_removed(self):
        first = [_prop(i, score=0.1) for i in range(10)]
        published = self._publish(first, now=NOW)
        shown = {e["player_id"] for e in published["all_bets"]}

        # Ten much better new entries arrive. Not one displaces a published
        # bet: the owner's answer refuses the newcomer, it does not withdraw
        # what a reader was already shown.
        better = [_prop(50 + i, score=99.0) for i in range(10)]
        row = self._publish(first + better, now=NOW + timedelta(hours=1))
        self.assertEqual(shown, {e["player_id"] for e in row["all_bets"]})
        self.assertEqual(10, len(row["ceiling_refused"]))

    def test_a_day_already_over_the_ceiling_is_preserved_and_frozen(self):
        """History is not rewritten to look compliant.

        A row carrying fourteen entries -- three real 2026-09-22 rows do --
        keeps all fourteen, and no further entry is admitted on top.
        """
        over = [_prop(i, score=1.0) for i in range(14)]
        card_ledger._ledger(self.path).append({
            "kind": card_ledger.KIND_PUBLISHED,
            "date": "2026-09-23",
            "published_utc": NOW.isoformat(),
            "rule": best_bets_card.V2.rule_id,
            "all_bets": over,
            "picks": over,
            "prop_picks": over,
            "fills": [],
            "withdrawn": [],
            "n_picks": 14,
            "n_fills": 0,
        })

        row = self._publish(over + [_prop(77, score=9.0)],
                            now=NOW + timedelta(hours=1))
        self.assertEqual(14, len(row["all_bets"]))
        self.assertNotIn(1077, {e["player_id"] for e in row["all_bets"]})
        self.assertIn(1077, {e["player_id"] for e in row["ceiling_refused"]})

    def test_a_later_clean_slate_gets_the_ordinary_ten_entry_rule(self):
        over = [_prop(i, score=1.0) for i in range(14)]
        card_ledger._ledger(self.path).append({
            "kind": card_ledger.KIND_PUBLISHED,
            "date": "2026-09-23",
            "published_utc": NOW.isoformat(),
            "rule": best_bets_card.V2.rule_id,
            "all_bets": over, "picks": over, "prop_picks": over,
            "fills": [], "withdrawn": [], "n_picks": 14, "n_fills": 0,
        })
        fresh = [_prop(i, score=1.0 - i / 100.0) for i in range(14)]
        row = self._publish(fresh, now=NOW + timedelta(days=1),
                            date="2026-09-24")
        self.assertEqual(10, len(row["all_bets"]))

    def test_a_withdrawn_entry_holds_no_slot(self):
        """It is off the card, so it must not consume room -- otherwise a
        day's withdrawals would silently shrink the card below ten."""
        first = [_prop(i, score=1.0 - i / 100.0) for i in range(10)]
        self._publish(first, now=NOW)

        # Entry 0's fresh read now hard-fails, withdrawing it; a new entry
        # should take the freed slot.
        failing = dict(first[0])
        failing["failed_gates"] = ["G2_BOOKS"]
        failing["entry_class"] = "pick"
        rest = first[1:]
        row = self._publish(rest + [failing, _prop(60, score=0.5)],
                            now=NOW + timedelta(hours=1))
        ids = {e["player_id"] for e in row["all_bets"]}
        self.assertLessEqual(len(row["all_bets"]), 10)
        self.assertIn(1060, ids)
        self.assertIn(1000, {e["player_id"] for e in row["withdrawn"]})


class LedgerAndHelperAgree(unittest.TestCase):
    """The rule is written twice on purpose -- once in card_ledger.py, where
    `V1_FINGERPRINT_FILES` can see it, and once in
    `src/appstate/ceiling_admission.py` for the reconciliation script. This
    is what stops the two drifting."""

    def test_same_admission_decision_on_the_same_inputs(self):
        carried = [_prop(i, score=1.0) for i in range(10)]
        fresh = [_prop(50 + i, score=2.0) for i in range(3)]
        for entry in carried:
            entry["locked"] = True

        helper_admitted, helper_refused = ceiling_admission.admit(
            carried, fresh, ceiling=best_bets_card.V2.ceiling)

        merged = list(carried) + list(fresh)
        keys = frozenset(card_ledger._v2_entry_key(e) for e in carried)
        ledger_refused = card_ledger._apply_ceiling_v2(
            merged, best_bets_card.V2, already_published_keys=keys)

        self.assertEqual(len(helper_admitted), len(merged))
        self.assertEqual(len(helper_refused), len(ledger_refused))
        self.assertEqual({e["player_id"] for e in helper_refused},
                         {e["player_id"] for e in ledger_refused})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
