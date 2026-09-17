"""T5 -- the `?rule=v2` API wiring (api/card.py, api/meta.py).

Direct function calls against `api.card`'s route functions (this repo's own
test style for the card routes -- see `tests/test_api_sport_param.py`),
with `src.report.card_v2` and `src.appstate.card_ledger` mocked so this
never reads a live store or the real schedule. `rule=None`/`rule="v1"`
paths are asserted BYTE-UNCHANGED (no new key, no branch entered) by
patching the v2 builder to raise if it is ever called on those paths.
"""

from __future__ import annotations

import unittest
from unittest import mock

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import card as card_mod
    from src.report import card as card_v1_mod
    from src.report import card_v2 as card_v2_mod


class _FakeState:
    def __init__(self, user_id="u1"):
        self.user_id = user_id


class _FakeRequest:
    def __init__(self, user_id="u1"):
        self.state = _FakeState(user_id)


def _v2_payload(date="2026-09-20"):
    return {
        "rule": "DAILY_CARD_BEST_BETS_V2", "date": date, "picks": [],
        "prop_picks": [], "fills": [], "withdrawn": [], "all_bets": [],
        "n_picks": 0, "n_fills": 0, "n_plus_money_picks": 0,
        "stale_board": None, "raw_pool_size": 0, "games_on_slate": 0,
        "empty_reason": "No priced board to evaluate for this date.",
        "basis": "basis", "disclaimer": "disclaimer",
    }


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class ResolveRule(unittest.TestCase):
    def test_none_resolves_to_active_card_rule(self):
        with mock.patch.object(card_v1_mod, "ACTIVE_CARD_RULE", "v1"):
            self.assertEqual("v1", card_mod._resolve_rule(None))

    def test_v2_resolves_to_v2(self):
        self.assertEqual("v2", card_mod._resolve_rule("v2"))

    def test_an_unknown_rule_is_a_400(self):
        with self.assertRaises(fastapi.HTTPException) as ctx:
            card_mod._resolve_rule("v3")
        self.assertEqual(400, ctx.exception.status_code)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class CardRouteRuleDispatch(unittest.TestCase):
    def test_default_rule_never_touches_card_v2(self):
        """No `rule` param at all -- every existing caller -- must reach
        exactly V1's branch. Patching `card_v2_for_date` to raise means
        this test fails loudly if the v1 default path is ever routed
        through v2 by mistake."""
        with mock.patch.object(card_v2_mod, "card_v2_for_date",
                               side_effect=AssertionError("v2 called on default rule")), \
             mock.patch.object(card_v1_mod, "frozen_card", return_value=None), \
             mock.patch("api.card._build_entries", return_value=([], [], {})), \
             mock.patch("api.card.opportunities_mod.build_opportunities",
                        return_value={"rows": []}):
            payload = card_mod.get_card_for_date(
                "2026-09-20", request=_FakeRequest())
        self.assertNotIn("raw_pool_size", payload)

    def test_rule_v2_serves_the_live_build_when_nothing_is_published(self):
        with mock.patch.object(card_v2_mod, "frozen_card_v2", return_value=None), \
             mock.patch.object(card_v2_mod, "card_v2_for_date",
                               return_value=_v2_payload()) as fake_build, \
             mock.patch("api.card._build_entries", return_value=([], [], {})), \
             mock.patch("api.card.opportunities_mod.build_opportunities",
                        return_value={"rows": []}):
            payload = card_mod.get_card_for_date(
                "2026-09-20", request=_FakeRequest(), rule="v2")
        self.assertTrue(fake_build.called)
        self.assertEqual("DAILY_CARD_BEST_BETS_V2", payload["rule"])
        self.assertIn("raw_pool_size", payload)

    def test_rule_v2_serves_the_frozen_row_when_one_is_published(self):
        frozen_row = dict(_v2_payload(), frozen=True, frozen_at="x")
        with mock.patch.object(card_v2_mod, "frozen_card_v2",
                               return_value=frozen_row), \
             mock.patch.object(card_v2_mod, "card_v2_for_date",
                               side_effect=AssertionError(
                                   "live build called despite a frozen row")):
            payload = card_mod.get_card_for_date(
                "2026-09-20", request=_FakeRequest(), rule="v2")
        self.assertTrue(payload["frozen"])

    def test_a_missing_frozen_parameter_file_is_a_503_not_a_500_or_empty_card(self):
        with mock.patch.object(card_v2_mod, "frozen_card_v2", return_value=None), \
             mock.patch.object(card_v2_mod, "card_v2_for_date",
                               side_effect=card_v2_mod.CardV2Error("missing")), \
             mock.patch("api.card._build_entries", return_value=([], [], {})), \
             mock.patch("api.card.opportunities_mod.build_opportunities",
                        return_value={"rows": []}):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                card_mod.get_card_for_date(
                    "2026-09-20", request=_FakeRequest(), rule="v2")
        self.assertEqual(503, ctx.exception.status_code)

    def test_today_route_also_forwards_the_rule(self):
        with mock.patch.object(card_v2_mod, "frozen_card_v2", return_value=None), \
             mock.patch.object(card_v2_mod, "card_v2_for_date",
                               return_value=_v2_payload()) as fake_build:
            card_mod.get_card_today(request=_FakeRequest(), rule="v2")
        self.assertTrue(fake_build.called)


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class CardRecordRuleDispatch(unittest.TestCase):
    def _record_v2_fixture(self):
        blank = {"days": 0, "wins": 0, "losses": 0, "pushes": 0, "voids": 0,
                "n_staked": 0, "profit_units": 0.0, "win_rate": None,
                "roi_pct": None}
        return {"since": None, "until": None, "main": dict(blank),
               "plus_money": dict(blank), "fills": dict(blank),
               "combined": dict(blank), "withdrawn": 0}

    def test_default_record_never_touches_record_v2(self):
        with mock.patch("src.appstate.card_ledger.record_v2",
                        side_effect=AssertionError("record_v2 called")), \
             mock.patch("src.appstate.card_ledger.record",
                        return_value={"days": 0, "wins": 0, "losses": 0,
                                      "pushes": 0, "voids": 0, "n_staked": 0}), \
             mock.patch("src.appstate.card_ledger.verify",
                        return_value=mock.Mock(ok=True, rows_checked=0)):
            payload = card_mod.get_card_record(request=_FakeRequest())
        self.assertNotIn("main", payload)

    def test_rule_v2_returns_main_plus_money_fills_and_combined_apart(self):
        with mock.patch("src.appstate.card_ledger.record_v2",
                        return_value=self._record_v2_fixture()):
            payload = card_mod.get_card_record(
                request=_FakeRequest(), rule="v2")
        for key in ("main", "plus_money", "fills", "combined"):
            self.assertIn(key, payload)
        self.assertEqual("v2", payload["rule"])
        # HONESTY CONSTRAINT 3: never a dollar value anywhere near the
        # record. This response is the object a page renders verbatim, so
        # it is checked here, not only in a copy-string scan.
        blob = str(payload)
        self.assertNotIn("$", blob)

    def test_rule_v2_never_sums_main_and_plus_money_into_one_untagged_figure(self):
        main = dict(self._record_v2_fixture()["main"], wins=10, losses=5, n_staked=15)
        plus = dict(self._record_v2_fixture()["plus_money"], wins=1, losses=4, n_staked=5)
        combined = dict(self._record_v2_fixture()["combined"], wins=11, losses=9, n_staked=20)
        fig = self._record_v2_fixture()
        fig.update(main=main, plus_money=plus, combined=combined)
        with mock.patch("src.appstate.card_ledger.record_v2", return_value=fig):
            payload = card_mod.get_card_record(request=_FakeRequest(), rule="v2")
        self.assertEqual(10, payload["main"]["wins"])
        self.assertEqual(1, payload["plus_money"]["wins"])
        self.assertEqual(11, payload["combined"]["wins"])


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class CardHistoryRuleDispatch(unittest.TestCase):
    def test_rule_v2_calls_history_v2_not_history(self):
        with mock.patch("src.appstate.card_ledger.history_v2",
                        return_value={"days": [], "total_days": 0,
                                      "truncated": False}) as fake_v2, \
             mock.patch("src.appstate.card_ledger.history",
                        side_effect=AssertionError("v1 history called")):
            payload = card_mod.get_card_history(
                request=_FakeRequest(), rule="v2")
        self.assertTrue(fake_v2.called)
        self.assertEqual([], payload["days"])


if __name__ == "__main__":
    unittest.main()
