"""The MLB card page after the value-picks pause (owner decision 2026-10-16):
the server's reason is the empty state, the links it sent are the ones drawn,
and the UFC paused page and every other state are not moved.

These RUN the real web/js/card.js under node (the fake DOM and stubbed `apiGet`
of tests/test_web_card_v2_render.py) and read back what a reader sees. The page
is fed what the route serves: the paused payload is built by the same helper the
route calls, not typed out by hand.

The node tests skip when node is not installed (the GitHub runner has it).
"""

# Copy updated per owner ruling 2026-10-20, complete-product positioning (no beta / early-access / paused hedging; invite wording).
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.appstate import mlb_public_card as mpc
from tests.test_ufc_public_card import EM_DASH
from tests.test_web_ufc_paused_page import _PausedPageHarness

PAUSED_DATE = "2026-10-17"
RECORD = {"days": 20, "n_staked": 178, "wins": 97, "losses": 81, "pushes": 0, "voids": 0,
          "profit_units": -1.42, "win_rate": 0.54, "chain_ok": True}

LAST_NIGHT = {
    "date": "2026-10-16", "sport": "mlb", "rule": "DAILY_CARD_BEST_BETS_V2", "frozen": True,
    "frozen_at": "2026-10-16T15:00:00+00:00", "prices_as_of": "2026-10-16T15:00:00+00:00",
    "picks": [{"sport": "mlb", "rank": 1, "market": "moneyline", "side": "home",
               "away_team": "Brewers", "home_team": "Cubs",
               "first_pitch_utc": "2026-10-16T23:40:00Z",
               "bet": "Cubs to win at -120", "price": -120, "books": 5,
               "label": "LEAN", "market_probability": 0.55, "why": []}],
    "disclaimer": "d", "basis": "b",
}


class _MlbPausedHarness(_PausedPageHarness):
    def mlb_page(self, payload, *, date, earlier=None):
        responses = [["/card/record", {"body": RECORD}],
                     [f"/card/{date}", {"body": payload}]]
        if earlier is not None:
            responses.append([f"/card/{earlier['date']}", {"body": earlier}])
        return self.run_page(responses, date=date, sport="mlb")


class TheMlbPausedPage(_MlbPausedHarness):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tmp = tempfile.TemporaryDirectory()
        cls._config_tmp = tmp
        config = Path(tmp.name) / "mlb_public_card.json"
        config.write_text(json.dumps({mpc.CONFIG_KEY: "2026-10-16"}), encoding="utf-8")
        cls.payload = mpc.paused_card(PAUSED_DATE, config)

    @classmethod
    def tearDownClass(cls):
        cls._config_tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        # last night's card is there to be found, and the old fallback WOULD
        # have put it on screen under the empty state
        self.out = self.mlb_page(self.payload, date=PAUSED_DATE, earlier=LAST_NIGHT)
        self.lower = self.out["text"].lower()

    def test_the_fixture_is_the_payload_the_route_serves(self):
        self.assertIs(self.payload["paused"], True)
        self.assertEqual(self.payload["picks"], [])
        self.assertEqual(self.payload["sport"], "mlb")
        self.assertEqual(self.payload["reason"], mpc.PAUSED_REASON)

    def test_the_reason_is_the_empty_state_word_for_word(self):
        self.assertIn("card-paused", self.out["hooks"])
        self.assertEqual(self.out["text"].count(mpc.PAUSED_REASON), 1)
        self.assertIn("card-paused-reason", self.out["hooks"])
        self.assertIs(self.out["rendered"], False)

    def test_it_is_labelled_paused_and_is_not_the_no_card_today_state(self):
        self.assertIn("NO PICKS FOR THIS DATE", self.out["text"])
        self.assertNotIn("NO CARD TODAY", self.out["text"])
        self.assertNotIn("card-empty", self.out["hooks"])

    def test_it_draws_the_links_the_server_sent_and_not_the_ufc_ones(self):
        for link in self.payload["links"]:
            self.assertIn(link["href"], self.out["hrefs"])
            self.assertIn(link["label"], self.out["text"])
        self.assertIn("card-record-link", self.out["hooks"])
        self.assertIn("card-paused-link-1", self.out["hooks"])
        self.assertIn("card-paused-link-2", self.out["hooks"])
        self.assertNotIn("#/ufc/record", self.out["hrefs"])
        self.assertNotIn("VIEW THE UFC RECORD", self.out["text"])
        self.assertNotIn("card-paused-mlb-link", self.out["hooks"])

    def test_it_draws_no_card_and_does_not_walk_back_to_last_nights(self):
        self.assertEqual(self.out["cards"], [])
        for hook in ("card-grid", "card-all-bets-grid", "card-older", "card-frozen", "card-live"):
            self.assertNotIn(hook, self.out["hooks"], hook)
        self.assertNotIn("LAST PUBLISHED CARD", self.out["text"])
        self.assertNotIn("Tomorrow's card posts", self.out["text"])
        self.assertNotIn("Cubs", self.out["text"])
        self.assertEqual(sorted(self.out["calls"]),
                         sorted([f"/card/{PAUSED_DATE}", "/card/record"]),
                         "the page asked for nothing but the date's card and the record")

    def test_the_record_strip_with_its_figures_is_not_drawn_under_it(self):
        self.assertNotIn("card-record", self.out["hooks"])
        for figure in ("97-81", "-1.42", "units"):
            self.assertNotIn(figure, self.out["text"], figure)

    def test_no_dash_no_bet_check_and_no_claim(self):
        self.assertNotIn(EM_DASH, self.out["text"])
        for word in ("bet check", "betcheck", "profit", "win rate", "guarantee"):
            self.assertNotIn(word, self.lower, word)
        for href in self.out["hrefs"]:
            self.assertNotIn("betcheck", href)

    def test_links_that_are_malformed_are_skipped_not_drawn(self):
        payload = {**self.payload, "links": [{"label": "ok", "href": "#/record-card"},
                                              {"label": 3, "href": "#/x"}, {"href": "#/y"}, None]}
        out = self.mlb_page(payload, date=PAUSED_DATE)
        self.assertIn("#/record-card", out["hrefs"])
        self.assertNotIn("#/x", out["hrefs"])
        self.assertNotIn("#/y", out["hrefs"])

    def test_a_paused_payload_with_no_links_still_shows_the_reason(self):
        payload = {k: v for k, v in self.payload.items() if k != "links"}
        out = self.mlb_page(payload, date=PAUSED_DATE)
        self.assertEqual(out["text"].count(mpc.PAUSED_REASON), 1)


class TheOtherMlbStatesAreNotMoved(_MlbPausedHarness):
    CUT_OFF = "2026-10-16"

    def test_only_a_paused_flag_that_is_exactly_true_is_the_paused_state(self):
        empty = {"date": self.CUT_OFF, "sport": "mlb", "rule": "DAILY_CARD_BEST_BETS_V2",
                 "frozen": False, "picks": [], "count": 0, "reason": "No games priced yet."}
        for value in (False, None, "true", 1, 0):
            with self.subTest(paused=value):
                out = self.mlb_page({**empty, "paused": value}, date=self.CUT_OFF)
                self.assertNotIn("card-paused", out["hooks"])
                self.assertIn("card-empty", out["hooks"])

    def test_the_ufc_paused_page_still_draws_its_own_links(self):
        from src.appstate import ufc_public_card as upc
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "ufc_public_card.json"
            config.write_text(json.dumps({upc.CONFIG_KEY: "2026-10-03"}), encoding="utf-8")
            payload = upc.paused_card("2026-10-10", config)
        self.assertNotIn("links", payload)
        out = self.run_page(
            [["/card/record?sport=mma", {"body": RECORD}],
             ["/card/2026-10-10?sport=mma", {"body": payload}]],
            date="2026-10-10", sport="mma")
        self.assertIn("#/ufc/record", out["hrefs"])
        self.assertIn("VIEW THE UFC RECORD", out["text"])


if __name__ == "__main__":
    unittest.main()
