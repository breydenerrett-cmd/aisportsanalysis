"""The UFC page after the pause (owner decision 2026-10-03): the server's reason
is the empty state, the record is linked, and nothing else about the page's
other states moves.

These RUN the real web/js/card.js under node (the fake DOM and stubbed `apiGet`
of tests/test_web_card_v2_render.py) and read back what a reader sees. The page
is fed what the route serves: the paused payload is built by the same helper the
route calls, not typed out by hand.

WHAT A READER MUST SEE, AND MUST NOT
------------------------------------
  * the reason sentence, word for word, as the page's empty state, labelled
    "PICKS PAUSED" and not "NO CARD TODAY";
  * a link to the UFC record (#/ufc/record), and one to tonight's MLB card;
  * no card, no walk-back to last night's picks (that fallback tells the reader
    "Tomorrow's card posts in the morning", which is false while the pause
    lasts), no record strip with a return figure under it;
  * no link or mention of the Bet Check tool, no em dash, no claim about profit,
    edge or results.

AND THE OTHER STATES STAY AS THEY WERE: an empty UFC card with an earlier card
behind it still walks back to it, an empty card with nothing behind it is still
"NO CARD TODAY", and only a payload whose `paused` is exactly `true` is the
paused state.

The node tests skip when node is not installed (the GitHub runner has it).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.appstate import ufc_public_card as upc
from tests.test_ufc_public_card import EM_DASH, THE_REASON
from tests.test_web_card_v2_render import NODE, _CardHarness

ROOT = Path(__file__).resolve().parent.parent
CARD_JS = (ROOT / "web" / "js" / "card.js").read_text(encoding="utf-8")
CARD_CSS = (ROOT / "web" / "css" / "card.css").read_text(encoding="utf-8")

PAUSED_DATE = "2026-10-10"
RECORD = {"days": 2, "n_staked": 6, "wins": 5, "losses": 1, "pushes": 0, "voids": 0,
          "profit_units": 1.23, "win_rate": 0.8333, "chain_ok": True}

LAST_NIGHT = {
    "date": "2026-10-09", "sport": "mma", "rule": "UFC_CARD_V1", "frozen": True,
    "frozen_at": "2026-10-09T18:11:11+00:00", "prices_as_of": "2026-10-09T18:11:11+00:00",
    "picks": [{"sport": "mma", "rank": 1, "market": "moneyline", "side": "home",
               "away_team": "A. Fighter", "home_team": "B. Fighter",
               "first_pitch_utc": "2026-10-09T23:40:00Z",
               "bet": "B. Fighter to win at -143 (consensus)", "price": -143, "books": 5,
               "label": "LEAN", "market_probability": 0.58, "why": []}],
    "disclaimer": "d", "basis": "b",
}


class _PausedPageHarness(_CardHarness):
    """_CardHarness renders one date's card with the record beside it. These
    tests also need to say what the OTHER days answer, so they hand it the
    stubbed responses directly."""

    def run_page(self, responses, *, date, sport="mma"):
        scenario = {"args": [{"date": date, "sport": sport}], "responses": responses}
        path = self._root / "scenario.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        env = dict(os.environ, TZ="America/Los_Angeles")
        proc = subprocess.run([NODE, str(self._root / "run.mjs"), str(path)], capture_output=True,
                              text=True, timeout=60, encoding="utf-8", env=env)
        if proc.returncode != 0:
            self.fail(f"node harness failed:\n{proc.stderr[-3000:]}")
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        out = json.loads(line[2:])
        self.assertIsNone(out["rejected"], out["rejected"])
        return out

    def page_for(self, payload, *, date, earlier=None):
        """The page for `date` whose card request answers `payload`. `earlier`
        is what the day before it answers (nothing, so a 404, when None)."""
        responses = [["/card/record?sport=mma", {"body": RECORD}],
                     [f"/card/{date}?sport=mma", {"body": payload}]]
        if earlier is not None:
            responses.append([f"/card/{earlier['date']}?sport=mma", {"body": earlier}])
        return self.run_page(responses, date=date)


class ThePausedPage(_PausedPageHarness):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tmp = tempfile.TemporaryDirectory()
        cls._config_tmp = tmp
        config = Path(tmp.name) / "ufc_public_card.json"
        config.write_text(json.dumps({upc.CONFIG_KEY: "2026-10-03"}), encoding="utf-8")
        cls.payload = upc.paused_card(PAUSED_DATE, config)

    @classmethod
    def tearDownClass(cls):
        cls._config_tmp.cleanup()
        super().tearDownClass()

    def setUp(self):
        # last night's card is there to be found, and the old fallback WOULD
        # have put it on screen under the empty state
        self.out = self.page_for(self.payload, date=PAUSED_DATE, earlier=LAST_NIGHT)
        self.lower = self.out["text"].lower()

    def test_the_fixture_is_the_payload_the_route_serves(self):
        """Guards the guard: a payload that stopped being paused would make
        every test below describe some other page."""
        self.assertIs(self.payload["paused"], True)
        self.assertEqual(self.payload["picks"], [])
        self.assertEqual(self.payload["reason"], THE_REASON)

    def test_the_reason_is_the_empty_state_word_for_word(self):
        self.assertIn("card-paused", self.out["hooks"])
        self.assertEqual(self.out["text"].count(THE_REASON), 1)
        self.assertIn("card-paused-reason", self.out["hooks"])
        self.assertIs(self.out["rendered"], False)

    def test_it_is_labelled_paused_and_is_not_the_no_card_today_state(self):
        self.assertIn("PICKS PAUSED", self.out["text"])
        self.assertNotIn("NO CARD TODAY", self.out["text"])
        self.assertNotIn("card-empty", self.out["hooks"])

    def test_it_links_the_ufc_record_and_tonights_mlb_card(self):
        self.assertIn("#/ufc/record", self.out["hrefs"])
        self.assertIn("#/today", self.out["hrefs"])
        self.assertIn("card-record-link", self.out["hooks"])
        self.assertIn("VIEW THE UFC RECORD", self.out["text"])

    def test_it_draws_no_card_and_does_not_walk_back_to_last_nights(self):
        self.assertEqual(self.out["cards"], [])
        for hook in ("card-grid", "card-all-bets-grid", "card-older", "card-frozen", "card-live"):
            self.assertNotIn(hook, self.out["hooks"], hook)
        self.assertNotIn("LAST PUBLISHED CARD", self.out["text"])
        self.assertNotIn("Tomorrow's card posts", self.out["text"])
        self.assertNotIn("B. Fighter", self.out["text"])
        self.assertEqual(sorted(self.out["calls"]),
                         sorted([f"/card/{PAUSED_DATE}?sport=mma", "/card/record?sport=mma"]),
                         "the page asked for nothing but today's card and the record")

    def test_the_record_strip_with_its_figures_is_not_drawn_under_it(self):
        self.assertNotIn("card-record", self.out["hooks"])
        self.assertNotIn("THE RECORD SO FAR", self.out["text"])
        for figure in ("5-1", "1.23", "units"):
            self.assertNotIn(figure, self.out["text"], figure)

    def test_no_bet_check_no_em_dash_and_no_claim(self):
        self.assertNotIn(EM_DASH, self.out["text"])
        for word in ("bet check", "betcheck", "profit", "edge", "roi", "win rate", "return",
                     "guarantee"):
            self.assertNotIn(word, self.lower, word)
        for href in self.out["hrefs"]:
            self.assertNotIn("betcheck", href)
            self.assertNotIn("#/odds", href)

    def test_the_one_experimental_notice_is_still_there_once(self):
        self.assertEqual(self.out["hooks"].count("experimental-notice"), 1)


class TheOtherStatesAreNotMoved(_PausedPageHarness):
    CUT_OFF = "2026-10-03"
    DAY_BEFORE = {**LAST_NIGHT, "date": "2026-10-02"}

    def empty_live_card(self, **extra):
        return {"date": self.CUT_OFF, "sport": "mma", "rule": "UFC_CARD_V1", "frozen": False,
                "picks": [], "count": 0, "reason": "No UFC bouts captured for this date.",
                **extra}

    def test_an_empty_ufc_card_still_walks_back_to_the_card_before_it(self):
        out = self.page_for(self.empty_live_card(), date=self.CUT_OFF, earlier=self.DAY_BEFORE)
        self.assertIn("/card/2026-10-02?sport=mma", out["calls"])
        self.assertIn("LAST PUBLISHED CARD", out["text"])
        self.assertIn("card-older", out["hooks"])
        self.assertNotIn("card-paused", out["hooks"])
        self.assertNotIn("PICKS PAUSED", out["text"])
        self.assertEqual(len(out["cards"]), 1)

    def test_an_empty_card_with_nothing_behind_it_is_still_no_card_today(self):
        out = self.page_for(self.empty_live_card(), date=self.CUT_OFF)
        self.assertIn("card-empty", out["hooks"])
        self.assertIn("NO CARD TODAY", out["text"])
        self.assertIn("No UFC bouts captured for this date.", out["text"])
        self.assertNotIn("card-paused", out["hooks"])

    def test_only_a_paused_flag_that_is_exactly_true_is_the_paused_state(self):
        for value in (False, None, "true", "yes", 1, 0):
            with self.subTest(paused=value):
                out = self.page_for(self.empty_live_card(paused=value), date=self.CUT_OFF)
                self.assertNotIn("card-paused", out["hooks"])
                self.assertIn("card-empty", out["hooks"])

    def test_a_ufc_card_with_picks_renders_its_picks_as_before(self):
        card = {**LAST_NIGHT, "date": self.CUT_OFF, "frozen": False}
        out = self.page_for(card, date=self.CUT_OFF)
        self.assertEqual(len(out["cards"]), 1)
        self.assertIn("B. Fighter to win at -143", out["cards"][0]["bet"])
        self.assertIn("card-record", out["hooks"], "the record strip is still under a real card")
        self.assertNotIn("card-paused", out["hooks"])


class TheSourceAndTheStyles(unittest.TestCase):
    def paused_card_source(self):
        start = CARD_JS.index("function pausedCard(")
        return CARD_JS[start:CARD_JS.index("\n}\n", start) + 3]

    def test_the_paused_state_is_decided_before_the_walk_back(self):
        paused = CARD_JS.index("payload.paused === true")
        walk_back = CARD_JS.index("await lastPublishedCard(payload.date")
        self.assertLess(paused, walk_back)

    def test_the_new_copy_has_no_dash_and_never_names_the_other_tool(self):
        source = self.paused_card_source()
        self.assertNotIn(EM_DASH, source)
        lowered = source.lower()
        for word in ("bet check", "betcheck", "#/odds"):
            self.assertNotIn(word, lowered, word)

    def test_the_class_the_page_uses_is_styled_and_readable_on_a_phone(self):
        self.assertIn("card2empty--paused", self.paused_card_source())
        rule = re.search(r"\.card2empty--paused \.card2empty__body \{([^}]*)\}", CARD_CSS)
        self.assertIsNotNone(rule, "the paused empty state has no style of its own")
        size = re.search(r"font-size:\s*(\d+(?:\.\d+)?)px", rule.group(1))
        self.assertIsNotNone(size)
        self.assertGreaterEqual(float(size.group(1)), 15.0)
        self.assertIn("font-style: normal", rule.group(1))

    def test_the_page_still_mounts_the_experimental_notice_exactly_once_in_source(self):
        """tests/test_web_sport_routes.py pins this count; the paused state must
        not add a second mount."""
        self.assertEqual(CARD_JS.count("experimentalNotice()"), 1)


if __name__ == "__main__":
    unittest.main()
