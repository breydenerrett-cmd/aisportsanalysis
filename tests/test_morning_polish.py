"""Five fixes found on LIVE production, 2026-10-22 ~09:35 UTC (hound DRAKEO, https://linehound.app/web/hound.html?id=u-d17e17fb4c).

  1. The feed's start word is the sport's own ("Match starts", "Tip-off"...), not "First pitch or kickoff" on a tennis match.
  2. Ticket reason text is written once at bet time into an append-only ledger and older rows carry raw sport keys
     ("GRIDIRON, NBA, WNBA and 4 more sports"); the label mapping happens at RENDER time, server side.
  3. "Unleash" meant two things. The owner's button on the hound page is now the studio's real Unleash (POST /unleash, the
     page half is tests/test_hounds_interact_web.py); a visitor's read-only run is "See what it would pick".
  4. The public live-status copy said every hound makes one-unit bets, which stopped being true when stakes became 0.5 to 5u.
  5. The stalled tennis ticket was not a stall (tests/test_live_settle_verify.py pins the story).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src.hounds import NOT_ADVICE, contract, ledgers, stats, user_spec
from tests.hounds_web_runner import HAS_NODE, WEB, run_js
from tests.test_hounds_interact_web import dog_routes, hook, page, q

ROOT = Path(__file__).resolve().parent.parent
RAW_KEY = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(user_spec.SPORT_PHRASE_LABELS) + r")(?![A-Za-z0-9_])")
RAW_REASON = "Rule 2: Stats Nerd: GRIDIRON, NBA, WNBA and 4 more sports moneylines and spreads: it backs either side when the market has moved."


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheFeedNamesTheStartInTheSportsOwnWord(unittest.TestCase):
    def feed(self, sport):
        ticket = {"selection": "Pick to win", "game": "A at B", "date": "2026-10-22", "price": 120, "price_average": 120,
                  "result": None, "status": "OPEN", "segment": "forward", "start_utc": "2026-10-22T07:20:00Z"}
        if sport is not None:
            ticket["sport"] = sport
        out = run_js("""import { buildFeed } from "%s";
const items = buildFeed({ voice: "generic", open: [%s], graded: [], streak: null, seed: "s" });
console.log(JSON.stringify(items.map((i) => i.text)));
""" % ((WEB / "js" / "hound-feed.js").as_uri(), json.dumps(ticket)))
        self.assertEqual(len(out), 1)
        return out[0]

    def test_a_tennis_match_does_not_start_with_a_first_pitch_or_a_kickoff(self):
        text = self.feed("tennis")
        self.assertIn("Match starts", text)
        self.assertNotRegex(text, r"(?i)first pitch|kickoff")

    def test_each_sport_has_its_own_word(self):
        words = {"mma": "Fight starts", "mlb": "First pitch", "nfl": "Kickoff", "ncaaf": "Kickoff", "nba": "Tip-off",
                 "wnba": "Tip-off", "nhl": "Puck drop", "soccer": "Kickoff", "tennis": "Match starts", "cricket": "Starts",
                 None: "Starts"}
        for sport, word in words.items():
            text = self.feed(sport)
            self.assertIn(f"{word} ", text, (sport, text))
            self.assertNotIn("First pitch or kickoff", text, sport)

    def test_the_helper_is_shared_and_not_a_copy_in_the_feed(self):
        feed = (WEB / "js" / "hound-feed.js").read_text(encoding="utf-8")
        board = (WEB / "js" / "hounds-board.js").read_text(encoding="utf-8")
        self.assertIn("export function startWord", board)
        self.assertIn("startWord(t.sport)", feed)
        self.assertNotIn("kickoff", re.sub(r"/\*.*?\*/", "", feed, flags=re.S).lower().replace("startword", ""))


class RawSportKeysAreMappedWhereTheReasonLeavesTheServer(unittest.TestCase):
    def bet(self, reason=RAW_REASON):
        return ledgers.Bet(hound_id="u-x", date="2026-10-22", event_id="e1", sport="tennis", market_key="h2h", side="home", price=130,
                           price_average=124, reason=reason, selection_text="Alexandra Eala to win", game_text="Diana Shnaider at Alexandra Eala")

    def test_the_stored_text_is_mapped_through_the_sport_labels(self):
        out = user_spec.plain_sport_keys(RAW_REASON)
        self.assertIn("CFL and UFL, NBA, WNBA and 4 more sports", out)
        self.assertIsNone(RAW_KEY.search(out), out)
        self.assertEqual(user_spec.plain_sport_keys("TENNIS first. then SOCCER and AFL."), "Tennis first. then soccer and Aussie rules.")

    def test_text_without_a_raw_key_comes_back_unchanged_and_prose_is_left_alone(self):
        for text in ("", "Inside the price band; 5 books posting.", "It backed the tennis side; Soccer fans, NBA and MLB are names."):
            self.assertEqual(user_spec.plain_sport_keys(text), text)
        self.assertEqual(user_spec.plain_sport_keys(None), "")

    def test_a_ticket_row_leaves_the_server_with_labels_and_the_ledger_row_is_untouched(self):
        bet = self.bet()
        row = stats.bet_row(bet, ("Diana Shnaider", "Alexandra Eala"))
        self.assertIsNone(RAW_KEY.search(json.dumps(contract.to_json(row))), row.reason)
        self.assertIn("CFL and UFL", row.reason)
        self.assertEqual(bet.reason, RAW_REASON, "the stored reason is append-only history; only the rendered copy changes")

    def test_no_internal_key_survives_any_key_in_any_position(self):
        for key in user_spec.SPORT_PHRASE_LABELS:
            for text in (f"{key} moneylines", f"on {key}, NBA and 2 more", f"backs {key}."):
                self.assertIsNone(RAW_KEY.search(user_spec.plain_sport_keys(text)), text)

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_the_rendered_hound_page_never_shows_a_raw_key_in_a_ticket(self):
        """The scan: serve the page tickets whose stored reason carries raw keys, as the server now emits them, and read every word the
        page rendered (the open table, the 'Why this bet' text, the settled list)."""
        mapped = contract.to_json(stats.bet_row(self.bet(), ("Diana Shnaider", "Alexandra Eala")))["reason"]
        routes = dog_routes()
        for payload in (routes["/hounds/closer"][1]["bets"], routes["/hounds/closer/bets"][1]):
            for item in payload["items"]:
                item["reason"] = mapped
        out = page(routes, queries=[q("main", "main"), q("reasons", ".hd-why", "texts")])
        seen = " ".join([str(out["final"].get("main") or "")] + list(out["final"].get("reasons") or []))
        self.assertIn("CFL and UFL", seen)
        self.assertIsNone(RAW_KEY.search(seen), seen[max(0, RAW_KEY.search(seen).start() - 60):][:160] if RAW_KEY.search(seen) else "")


class TheOwnersUnleashSaysWhatThePreviewSays(unittest.TestCase):
    """Unleash became the hound page's only button for an owner, so the empty-day words the preview always carried (which games started,
    the next game, what is live elsewhere; tests/test_live_board.py pins how the page draws them) must come from Unleash too."""

    def test_day_lines_are_the_same_words_the_preview_builds(self):
        import os
        import tempfile
        from unittest import mock
        from src.hounds import user_engine as eng
        from src.hounds.interact import fire
        from tests.test_hounds_interact_fire import NOW, dog_of, rows_for
        from tests._hounds_user_fixtures import standard_rows
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(eng, "ledger_path", lambda p=None: p or os.path.join(tmp, "u.jsonl")):
                dog = dog_of(price_min=150, price_max=250)          # nothing fits: the empty-day case
                games = fire.load_games(dog.hound["spec"]["sports"], NOW, rows_for(standard_rows()))
                preview = fire.fire_user(dog, now=NOW, games=games, ledger=os.path.join(tmp, "u.jsonl"))
        lines = fire.day_lines(dog.hound["spec"], games, NOW)
        self.assertEqual(lines["slate"], preview["slate"])
        self.assertEqual(lines["next_game"], preview["next_game"])
        self.assertEqual(lines["live_elsewhere"], preview["live_elsewhere"])

    def test_a_hound_with_a_pick_gets_no_next_game_line(self):
        from src.hounds.interact import fire
        from tests.test_hounds_interact_fire import NOW, dog_of, rows_for
        from tests._hounds_user_fixtures import standard_rows
        dog = dog_of()
        games = fire.load_games(dog.hound["spec"]["sports"], NOW, rows_for(standard_rows()))
        self.assertIsNone(fire.day_lines(dog.hound["spec"], games, NOW, have_picks=True)["next_game"])


class TheLiveStatusCopyIsTrue(unittest.TestCase):
    # "One unit is $25 at your unit size" (a definition, hounds.html) is true; "one-unit bets" and "one unit a bet" are the false claim
    CLAIM = re.compile(r"one-unit|1-unit|\bone unit a bet\b|\b1 unit a bet\b", re.I)

    def test_the_envelope_line_no_longer_claims_one_unit_bets(self):
        self.assertIsNone(self.CLAIM.search(NOT_ADVICE), NOT_ADVICE)
        self.assertTrue(NOT_ADVICE.startswith("Paper only, not advice."))
        self.assertIn("no money is staked", NOT_ADVICE)
        self.assertEqual(contract.envelope({"x": 1})["not_advice"], NOT_ADVICE)

    def test_the_basis_line_and_the_public_pages_do_not_claim_it_either(self):
        self.assertIsNone(self.CLAIM.search(contract.BASIS), contract.BASIS)
        self.assertNotRegex(contract.BASIS, r"\b[Dd]ogs?\b")
        for name in ("desk.html", "hounds.html", "landing.html", "hound.html", "kennel.html"):
            text = (WEB / name).read_text(encoding="utf-8")
            self.assertIsNone(self.CLAIM.search(text), (name, self.CLAIM.search(text) and self.CLAIM.search(text).group(0)))
        self.assertNotIn("one unit a bet", (WEB / "js" / "hounds-core.js").read_text(encoding="utf-8"))
        self.assertNotIn("1 unit a bet", (WEB / "js" / "hounds-core.js").read_text(encoding="utf-8"))

    def test_the_status_endpoint_carries_the_new_line(self):
        try:
            from fastapi import Response
            from api import hounds_live
        except ImportError:
            self.skipTest("FastAPI is not installed (the Linux no-FastAPI run)")
        body = hounds_live.live_status(Response(), _rl=None)
        self.assertEqual(body["not_advice"], NOT_ADVICE)


if __name__ == "__main__":
    unittest.main()
