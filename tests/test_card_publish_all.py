"""T5 -- `src.report.card.publish_all`.

Covers what `src.cli.cmd_card`'s `--rule all` branch and (later) T6's
scheduled `--rule all` call both depend on: one call that publishes V1, V2
and V2's three registered shadows (A, C, E -- there is no shadow D,
registration section 10) from ONE already-fetched board, without ever
touching a network client itself. Everything here is mocked at the
`card_v2`/`card_ledger` seam, matching the discipline
`tests/test_cli_card_v2_publish.py` already uses -- no live-store read, no
disk write.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.report import card


def _v2_payload(rule_id: str, n_picks: int = 1) -> dict:
    return {
        "date": "2026-09-20", "rule": rule_id,
        "games_on_slate": 1, "raw_pool_size": 1,
        "n_picks": n_picks, "n_fills": 0, "n_plus_money_picks": 0,
        "picks": [], "prop_picks": [], "fills": [], "withdrawn": [],
        "all_bets": [],
    }


class PublishAllTests(unittest.TestCase):
    def test_publishes_v1_v2_and_all_three_shadows_only(self):
        """Exactly five rule names come back -- v1 plus the four v2-family
        rules -- and "shadow-d" is never one of them. This is the direct
        behavioral pin for the plan's stale "shadows A, C, D and E" line
        (docs/CARD_V2_BUILD_PLAN.md's T5 row): the very next line of that
        same section says there is no shadow-d target, and this test
        proves `publish_all` follows that correction, not the typo.
        """
        seen_params = []

        def _fake_card_v2_for_date(entries, opportunity_rows, *, date, now,
                                   params):
            seen_params.append(params.rule_id)
            return _v2_payload(params.rule_id)

        with mock.patch("src.report.card_v2.card_v2_for_date",
                        side_effect=_fake_card_v2_for_date), \
             mock.patch("src.appstate.card_ledger.publish_v2",
                        side_effect=lambda card, **kw: {"n_picks": card["n_picks"],
                                                        "n_fills": 0,
                                                        "already_published": False}), \
             mock.patch("src.appstate.card_ledger.publish",
                        return_value={"picks": [], "already_published": False}):
            result = card.publish_all(
                "2026-09-20", entries=[], opportunity_rows=[],
                v1_card={"date": "2026-09-20", "picks": []})

        self.assertEqual(set(result), {"v1", "v2", "shadow-a", "shadow-c",
                                       "shadow-e"})
        self.assertNotIn("shadow-d", result)
        self.assertEqual(len(seen_params), 4)  # v2 + 3 shadows, never a 5th

    def test_no_shadow_d_anywhere_in_the_rule_table(self):
        """A second, independent pin: even if a future edit renamed a key,
        the underlying RuleParams objects `publish_all` reaches must never
        include one named for a deregistered shadow D."""
        from src.analysis import best_bets_card

        seen = []
        with mock.patch("src.report.card_v2.card_v2_for_date",
                        side_effect=lambda *a, params, **k: seen.append(params) or
                        _v2_payload(params.rule_id)), \
             mock.patch("src.appstate.card_ledger.publish_v2",
                        return_value={"n_picks": 0, "n_fills": 0}):
            card.publish_all("2026-09-20", entries=[], opportunity_rows=[])

        self.assertFalse(hasattr(best_bets_card, "SHADOW_D"))
        for params in seen:
            self.assertNotIn("SHADOW_D", params.rule_id)

    def test_v1_only_when_no_v1_card_given(self):
        """A caller that only wants the v2-family (v1_card=None, e.g. a
        preview-only path) gets no "v1" key at all -- publish_all never
        invents a V1 publish decision of its own."""
        with mock.patch("src.report.card_v2.card_v2_for_date",
                        side_effect=lambda *a, params, **k: _v2_payload(params.rule_id)), \
             mock.patch("src.appstate.card_ledger.publish_v2",
                        return_value={"n_picks": 0, "n_fills": 0}), \
             mock.patch("src.appstate.card_ledger.publish",
                        side_effect=AssertionError("v1 publish called with no v1_card")):
            result = card.publish_all("2026-09-20", entries=[], opportunity_rows=[])
        self.assertNotIn("v1", result)
        self.assertEqual(set(result), {"v2", "shadow-a", "shadow-c", "shadow-e"})

    def test_a_missing_frozen_param_file_skips_the_v2_family_not_v1(self):
        """`CardV2Error` (the frozen-parameter file missing or unreadable,
        registration 11.2/G9) blocks every v2-family rule identically --
        this must not also lose V1's own publish, which reads no frozen
        file at all."""
        from src.report import card_v2 as card_v2_mod

        with mock.patch("src.report.card_v2.card_v2_for_date",
                        side_effect=card_v2_mod.CardV2Error("missing frozen file")), \
             mock.patch("src.appstate.card_ledger.publish",
                        return_value={"picks": [], "already_published": False}) as pub:
            result = card.publish_all(
                "2026-09-20", entries=[], opportunity_rows=[],
                v1_card={"date": "2026-09-20", "picks": []})
        self.assertEqual(result, {"v1": pub.return_value})

    def test_calls_no_network_or_capture_client(self):
        """`publish_all` takes `entries`/`opportunity_rows` already built --
        it must never import or call a live provider itself, which is what
        makes calling it once per rule (four rule builds, one fetch) cost
        no additional capture-client call (registration 17.6)."""
        with mock.patch("src.providers.mlb.fetch_games",
                        side_effect=AssertionError("publish_all fetched games itself")), \
             mock.patch("src.report.card_v2.card_v2_for_date",
                        side_effect=lambda *a, params, **k: _v2_payload(params.rule_id)), \
             mock.patch("src.appstate.card_ledger.publish_v2",
                        return_value={"n_picks": 0, "n_fills": 0}):
            card.publish_all("2026-09-20", entries=[], opportunity_rows=[])


if __name__ == "__main__":
    unittest.main()
