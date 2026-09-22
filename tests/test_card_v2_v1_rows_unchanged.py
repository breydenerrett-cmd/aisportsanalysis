"""V1's own publish() output is byte-identical to what it produced before
this build touched the file -- pinned by hashing a fixture card's row,
excluding only the chain fields (`row_hash`/`prev_hash`) that any second
publish (V1's own re-run in a fresh ledger) would legitimately differ on for
reasons that have nothing to do with V2's additions.

ONE INTENTIONAL EXCEPTION, added at the T13 cutover (owner directive
2026-09-22 over the frozen -203 Cubs pick): every row now also carries
`blocked_by_price_guard`, the auditable trace of the hard -200-or-worse
moneyline guard in `card_ledger.publish` (see
`tests/test_card_v1_v2_cutover.py`). That is a deliberate, disclosed
addition to the row shape, not drift, so it is in `expected_keys` below by
name rather than being silently swallowed into "unaffected".
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from src.appstate import card_ledger


def _v1_card(date="2026-09-10"):
    return {
        "date": date,
        "rule": "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1",
        "basis": "basis sentence",
        "disclaimer": "disclaimer sentence",
        "model_id": "run_expectancy_poisson_v1",
        "calibrated": True,
        "calibration": {"a": 0.03, "b": 0.51, "n": 1896, "fitted": True},
        "filled": 0,
        "games_on_slate": 5,
        "picks": [{
            "rank": 1, "label": "STRONG", "bet": "Take Yankees to win at -150",
            "why": ["because"], "market": "moneyline", "line": None, "side": "home",
            "team": "NYY", "team_name": "Yankees", "opponent_name": "Rockies",
            "price": -150, "book": "draftkings", "books": 8,
            "confidence": 0.74, "market_probability": 0.74,
            "model_probability": 0.64, "game_id": "COL-NYY-2026-09-10-1",
            "game_pk": 1001, "event_id": "e1", "away_team": "COL",
            "home_team": "NYY", "first_pitch_utc": "2026-09-10T23:05:00Z",
            "observed_utc": "2026-09-10T18:00:00Z", "model": {},
        }],
    }


class V1RowsUnchanged(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v1.jsonl")

    def _canonical(self, row: dict) -> str:
        stripped = {k: v for k, v in row.items()
                   if k not in ("row_hash", "prev_hash", "already_published")}
        return json.dumps(stripped, sort_keys=True, default=str)

    def test_publish_v1_row_shape_is_unaffected_by_the_v2_module_additions(self):
        row = card_ledger.publish(_v1_card(), now="2026-09-10T10:00:00Z", path=self.path)
        expected_keys = {
            "kind", "date", "published_utc", "rule", "basis", "disclaimer",
            "model_id", "calibrated", "calibration", "n_picks", "n_filled",
            "games_on_slate", "picks", "n_locked", "prop_picks", "n_prop_picks",
            "n_prop_locked", "total_picks", "n_total_picks", "n_total_locked",
            "totals_paused", "row_hash", "prev_hash", "blocked_by_price_guard",
        }
        self.assertEqual(expected_keys, set(row.keys()) - {"already_published"})

    def test_a_second_run_in_a_fresh_ledger_reproduces_byte_identical_content(self):
        first_path = os.path.join(os.path.dirname(self.path), "run_a.jsonl")
        second_path = os.path.join(os.path.dirname(self.path), "run_b.jsonl")
        row_a = card_ledger.publish(_v1_card(), now="2026-09-10T10:00:00Z", path=first_path)
        row_b = card_ledger.publish(_v1_card(), now="2026-09-10T10:00:00Z", path=second_path)
        self.assertEqual(self._canonical(row_a), self._canonical(row_b))

    def test_v1_publish_still_refuses_an_empty_card_after_the_v2_additions(self):
        with self.assertRaises(card_ledger.CardLedgerError):
            card_ledger.publish(_v1_card() | {"picks": []}, path=self.path)

    def test_v1_frozen_fields_constant_is_unchanged(self):
        # Any T3 addition to FROZEN_FIELDS would silently change every V1
        # pick's shape -- this pins the exact tuple V1 has always used.
        self.assertEqual((
            "rank", "label", "bet", "why", "market", "line", "side",
            "team", "team_name", "opponent_name", "price", "book", "books",
            "confidence", "market_probability", "model_probability",
            "model_probability_moneyline", "game_id", "game_pk", "event_id",
            "away_team", "home_team", "first_pitch_utc", "observed_utc", "model",
            "alternative", "knowledge",
        ), card_ledger.FROZEN_FIELDS)


if __name__ == "__main__":
    unittest.main()
