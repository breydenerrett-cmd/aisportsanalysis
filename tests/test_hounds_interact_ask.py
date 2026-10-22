"""Ask your dog (src/hounds/interact/ask.py): the intent matcher over 20+ phrasings, and the answers.

No model is called anywhere: the last test reads the package's source to prove it imports no client library.
The context is an in-memory dog with a handful of tickets, so every number an answer quotes can be checked
against the fixture.
"""

from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.hounds.interact import ask

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "hounds" / "interact"
CLAIMS = re.compile(r"\block\b|\bedge\b|guarantee|sure thing|can'?t lose|free money|\bprofit|\bev\b|expected value|!", re.I)


def ticket(date, game, selection, price, result, *, best=None, book="book_b", n=5, status=None, units=None,
           reason="Rule: the underdog. It backed the away side."):
    return {"hound_id": "u-1", "date": date, "game": game, "market": "h2h", "selection": selection, "line": None,
            "price": best if best is not None else price, "price_average": price, "book": book, "book_count": n,
            "result": result, "units": units, "clv_pts": None, "who_decided": "rule", "reason": reason,
            "segment": "forward", "start_utc": f"{date}T23:10:00Z", "recorded_utc": f"{date}T21:10:00Z",
            "status": status or ("GRADED" if result else "OPEN")}


TICKETS = [
    ticket("2026-10-19", "Tampa Bay Rays @ Cleveland Guardians", "Cleveland Guardians to win", 131, None),
    ticket("2026-10-18", "Boston Red Sox @ Seattle Mariners", "Boston Red Sox to win", 125, "win", best=130, units=1.3),
    ticket("2026-10-17", "Texas Rangers @ Houston Astros", "Under 8.5", -105, "loss", units=-1.0),
]

SUMMARY = {
    "id": "u-1", "name": "Dog Days", "sports": ["MLB"], "open_bets": 1,
    "record": {"bets": 12, "wins": 6, "losses": 6, "pushes": 0, "voids": 0,
               "units_average_price": -0.4, "units_recorded_price": 0.2},
    "form": {"streak": {"kind": "L", "length": 2}, "last7": {"bets": 5, "wins": 2, "losses": 3, "units": -1.1},
             "best_bet": {"date": "2026-10-18", "game": "Boston Red Sox @ Seattle Mariners",
                          "selection": "Boston Red Sox to win", "price": 125, "units": 1.25},
             "worst_beat": {"date": "2026-10-17", "game": "Texas Rangers @ Houston Astros",
                            "selection": "Under 8.5", "price": -105, "units": -1.0}},
    "clv": {"n": 8, "mean_pts": 0.4},
    "verdict": {"label": "TOO EARLY", "sentence": "Not enough bets with a measurable closing price to say anything yet."},
}

NOW = datetime(2026, 10, 19, 21, 0, tzinfo=timezone.utc)
RULE_REASON = "Rule 2: Stats Nerd: average price between +100 and +250 across at least 3 books. It backed the away side at +131."

FIRE_WITH_PICK = {
    "picks": [{"event_id": "e-cle", "market": "moneyline", "market_label": "Moneyline", "side": "away",
               "selection": "Cleveland Guardians to win", "game": "Tampa Bay Rays @ Cleveland Guardians", "sport": "MLB",
               "price_average": 131, "price_best": 136, "best_book": "betonlineag", "before_lock": True,
               "start_utc": "2026-10-19T23:10:00Z", "day_label": "Today", "n_books": 11, "stale": False,
               "board_age_minutes": 5, "over_daily_limit": False, "reason": RULE_REASON}],
    "recorded": [], "closest_misses": [], "games": [], "headline": "1 pick qualifies on the latest stored boards."}

FIRE_NOTHING = {
    "picks": [], "headline": "Nothing qualifies right now.",
    "closest_misses": [{"game": "Washington Commanders @ San Francisco 49ers",
                        "why": "Washington Commanders +7.5 is -111 on the board, shorter than your band of +100 to +250: 2.6 points of win probability from the nearest limit, +100."}],
    "games": [{"game": "Washington Commanders @ San Francisco 49ers", "start_utc": "2026-10-20T00:15:00Z",
               "markets": [{"market": "spread", "status": "miss", "code": "outside_price_band",
                            "why": "Washington Commanders +7.5 is -111 on the board, shorter than your band."}]},
              {"game": "New England Patriots @ Chicago Bears", "start_utc": "2026-10-23T00:15:00Z",
               "markets": [{"market": "moneyline", "status": "pick", "selection": "New England Patriots to win",
                            "price_average": 127, "why": "x"}]}]}


def context(**over) -> ask.AskContext:
    base = dict(dog_id="u-1", name="Dog Days", kind="user", catchphrase="Fetch the plus money.",
                rule_text="Moneyline, MLB. Bet the underdog when its price is +100 to +250.",
                rule_english="I back the underdog on MLB moneylines when the price is +100 to +250.",
                spec={"lock_minutes": 120, "max_bets_per_day": 2, "min_books": 3}, summary=SUMMARY,
                tickets=list(TICKETS), feedback={"good": 7, "bad": 2, "notes": 3, "suggestions": 1},
                tips=[], is_owner=False, today="2026-10-19", fire_fn=lambda: FIRE_WITH_PICK, now=NOW)
    base.update(over)
    return ask.AskContext(**base)


# every phrasing a person might plausibly type, and the intent it must land on
PHRASINGS = [
    ("What rules would you change to find more relevant bets today? I don't like that you won't take a single bet on anything today", "retune"),
    ("Why didn't you bet the Yankees?", "why_not"),
    ("why did you skip the Rays", "why_not"),
    ("why did you pass on Cleveland", "why_not"),
    ("why no bet on the Guardians game", "why_not"),
    ("didn't you bet the over tonight?", "why_not"),
    ("Why did you bet Boston?", "why_bet"),
    ("Explain that pick", "why_bet"),
    ("what made you take Cleveland", "why_bet"),
    ("how come you backed the underdog", "why_bet"),
    ("What did you bet today?", "today"),
    ("what bets do you have open", "today"),
    ("show me your latest bet", "today"),
    ("what was your last bet", "today"),
    ("What did you bet yesterday?", "today"),
    ("What would you bet right now?", "picks_now"),
    ("any picks right now?", "picks_now"),
    ("what do you like tonight", "picks_now"),
    ("fire", "picks_now"),
    ("what's your pick", "picks_now"),
    ("What are you thinking tonight?", "picks_now"),
    ("How are you doing?", "record"),
    ("what's your record", "record"),
    ("are you any good", "record"),
    ("how many units are you up", "record"),
    ("what's your CLV", "record"),
    ("What's your best bet?", "best_worst"),
    ("worst bet?", "best_worst"),
    ("biggest win so far", "best_worst"),
    ("what was your worst loss", "best_worst"),
    ("What are your rules?", "rules"),
    ("how do you pick games", "rules"),
    ("explain your strategy", "rules"),
    ("How do I make you better?", "improve"),
    ("can I train you", "improve"),
    ("how do I improve you", "improve"),
    ("what do fans think?", "fans"),
    ("any feedback on you", "fans"),
    ("what has the coach said about you", "coach"),
    ("what would you have taken today pre market", "picks_earlier_today"),
    ("what would you have done this week", "backtest_window"),
    ("what is a spread", "explain_market"),
    ("help", "help"),
    ("who are you", "hello"),
    ("hi", "hello"),
    ("banana smoothie recipe", "fallback"),
    ("what's the weather in Boston", "fallback"),
    ("asdf", "fallback"),
    ("", "fallback"),
]


class TheMatcher(unittest.TestCase):
    def test_every_phrasing_lands_on_its_intent(self):
        wrong = []
        for text, intent in PHRASINGS:
            got = ask.answer(text, context())["intent"]
            if got != intent:
                wrong.append((text, intent, got))
        self.assertEqual(wrong, [])
        self.assertGreaterEqual(len(PHRASINGS), 40)

    def test_punctuation_case_and_apostrophes_do_not_matter(self):
        for text in ("WHAT'S YOUR RECORD???", "whats  your record", "What’s your record"):
            self.assertEqual(ask.classify(text), "record", text)

    def test_the_intents_are_a_closed_set_and_feedback_can_name_them(self):
        got = {ask.answer(text, context())["intent"] for text, _ in PHRASINGS}
        self.assertTrue(got <= set(ask.ANSWER_KINDS))
        self.assertEqual(got, set(ask.ANSWER_KINDS))        # every kind is reachable


class TheAnswers(unittest.TestCase):
    def say(self, text, **over):
        return ask.answer(text, context(**over))

    def test_what_did_you_bet_today_lists_todays_tickets_with_price_and_state(self):
        out = self.say("What did you bet today?")
        self.assertIn("Cleveland Guardians to win", out["answer"])
        self.assertIn("+131", out["answer"])
        self.assertIn("still open", out["answer"])
        self.assertNotIn("Boston Red Sox", out["answer"])               # yesterday's ticket is not today's
        self.assertEqual(out["tickets"][0]["key"], "2026-10-19|Cleveland Guardians to win")

    def test_yesterday_lists_yesterdays(self):
        out = self.say("What did you bet yesterday?")
        self.assertIn("Boston Red Sox to win", out["answer"])
        self.assertIn("it won", out["answer"])
        self.assertIn("best +130 at book_b", out["answer"])

    def test_a_day_with_no_ticket_says_so_and_points_at_the_last_one(self):
        out = self.say("What did you bet today?", today="2026-10-25")
        self.assertIn("I have no tickets today", out["answer"])
        self.assertIn("My last one was on Oct 19", out["answer"])

    def test_why_did_you_bet_gives_the_rule_the_reason_the_timing_and_the_result(self):
        out = self.say("Why did you bet Boston?")
        a = out["answer"]
        self.assertIn("I took Boston Red Sox to win in Boston Red Sox @ Seattle Mariners at +125", a)
        self.assertIn("5 books were quoting it", a)
        self.assertIn("My rule: I back the underdog", a)                  # the spec-to-English line, first person
        self.assertIn("The reason on the ticket: Rule: the underdog.", a)
        self.assertIn("2 hours before the start", a)
        self.assertIn("it won (+1.25u)", a)                               # units at the AVERAGE price, +125
        self.assertEqual(out["intent"], "why_bet")

    def test_why_with_no_team_explains_the_newest_open_ticket(self):
        out = self.say("why did you make that bet")
        self.assertIn("Cleveland Guardians to win", out["answer"])
        self.assertIn("it is still open", out["answer"])

    def test_a_dog_with_no_tickets_does_not_invent_a_reason(self):
        out = self.say("why did you bet that", tickets=[], summary=dict(SUMMARY, record={"bets": 0}))
        self.assertIn("I have not recorded a ticket yet", out["answer"])

    def test_how_are_you_doing_states_the_sample_and_calls_it_small(self):
        out = self.say("How are you doing?")
        a = out["answer"]
        self.assertIn("12 graded bets, a small sample", a)
        self.assertIn("6-6", a)
        self.assertIn("-0.40u at the average price", a)
        self.assertIn("2-loss run", a)
        self.assertIn("Last 7 days: 2-3 over 5 bets", a)
        self.assertIn("+0.4 points over 8 measurable bets", a)
        self.assertIn("The referee's read: Not enough bets", a)
        self.assertIn("Fetch the plus money.", a)                         # the dog's own line

    def test_a_record_with_no_graded_bets_says_so(self):
        out = self.say("how are you doing", summary=dict(SUMMARY, record={"bets": 0}, open_bets=2))
        self.assertIn("no graded bets yet", out["answer"])
        self.assertIn("2 open tickets", out["answer"])

    def test_best_and_worst_come_from_the_forms_own_picks(self):
        out = self.say("what's your best and worst bet")
        self.assertIn("My best bet: Boston Red Sox to win on Oct 18", out["answer"])
        self.assertIn("+1.25u", out["answer"])
        self.assertIn("My worst beat", out["answer"])
        self.assertIn("Under 8.5", out["answer"])
        self.assertIn("out of 12 graded bets, a small sample", out["answer"])

    def test_best_alone_does_not_dump_the_worst(self):
        out = self.say("what was your best bet")
        self.assertIn("My best bet", out["answer"])
        self.assertNotIn("worst beat", out["answer"])

    def test_what_would_you_bet_now_is_one_short_line_then_the_pick_card(self):
        out = self.say("What would you bet right now?")
        self.assertLessEqual(len(out["lines"]), 2)
        self.assertIn("Cleveland Guardians to win", out["lines"][0])
        self.assertIn("+131", out["lines"][0])
        card = out["cards"][0]
        self.assertEqual((card["selection"], card["price_text"], card["game"]), ("Cleveland Guardians to win", "+131", "Tampa Bay Rays @ Cleveland Guardians"))
        self.assertEqual(card["when"], "Today 7:10 pm ET")
        self.assertEqual(card["stake"], "$10")                            # the reference account's unit, when the asker sent no sizing
        # the rule text is NEVER inline: not in a line, not on the card; it sits behind "How I checked it"
        self.assertNotIn("Rule 2", out["answer"])
        self.assertEqual(card["reason"], "")
        self.assertEqual(out["details"]["title"], "How I checked it")
        self.assertTrue(any("Rule 2: Stats Nerd" in line for line in out["details"]["lines"]))
        self.assertIn("My rule: I back the underdog", " ".join(out["details"]["lines"]))
        self.assertIn("21+", out["fine"])

    def test_the_stake_on_the_card_is_the_askers_sizing(self):
        from src.hounds import unit_size
        fixed = ask.answer("What would you bet right now?", context(sizing=unit_size.Sizing("fixed", 50.0, None, 1000.0)))
        self.assertEqual(fixed["cards"][0]["stake"], "$50")
        pct = ask.answer("What would you bet right now?", context(sizing=unit_size.Sizing("percent", None, 2.0, 1000.0)))
        self.assertEqual(pct["cards"][0]["stake"], "2% of bankroll")

    def test_nothing_fresh_says_so_in_its_voice_and_names_the_next_game_without_listing_started_ones(self):
        nothing = dict(FIRE_NOTHING, recorded=[], slate={"line": "Tonight's games already started: Mets @ Braves (7:10 pm ET). Next games I can bet: Thursday."},
                       games_considered=0)
        out = self.say("What would you bet right now?", fire_fn=lambda: nothing)
        self.assertEqual(out["cards"], [])
        self.assertEqual(len(out["lines"]), 1)
        self.assertNotIn("Mets @ Braves", out["answer"])                  # a started game is never filler
        self.assertNotIn("already started", out["answer"])
        self.assertNotIn("Closest", out["answer"])                        # the near misses sit behind "How I checked it"
        self.assertTrue(any("Closest: Washington Commanders" in line for line in out["details"]["lines"]))

    def test_nothing_fresh_names_the_next_game_it_will_check(self):
        nothing = dict(FIRE_NOTHING, recorded=[], games_considered=0,
                       games=[{"event_id": "e-later", "game": "New England Patriots @ Chicago Bears", "start_utc": "2026-10-23T00:15:00Z"}])
        out = self.say("What would you bet right now?", fire_fn=lambda: nothing)
        self.assertIn("Next game I'll check: New England Patriots @ Chicago Bears", out["lines"][0])

    def test_a_ticket_it_already_holds_is_never_the_answer(self):
        held = dict(FIRE_WITH_PICK, recorded=[{"event_id": "e-cle", "market": "moneyline", "side": "away", "game": "Tampa Bay Rays @ Cleveland Guardians",
                                              "selection": "Cleveland Guardians to win", "price_average": 131, "start_utc": "2026-10-19T23:10:00Z"}])
        out = self.say("What would you bet right now?", fire_fn=lambda: held)
        self.assertEqual(out["cards"], [])
        self.assertNotIn("Cleveland Guardians to win", out["answer"])
        self.assertNotIn("Already on my record", out["answer"])

    def test_the_owners_manual_pick_is_held_too(self):
        manual = [{"event_id": "e-cle", "market": "moneyline", "side": "away", "game": "Tampa Bay Rays @ Cleveland Guardians",
                   "selection": "Cleveland Guardians to win", "start_utc": "2026-10-19T23:10:00Z", "kind": "manual"}]
        out = self.say("What would you bet right now?", manual=manual)
        self.assertEqual(out["cards"], [])

    def test_the_other_side_of_a_game_it_holds_is_never_offered(self):
        held = dict(FIRE_WITH_PICK, recorded=[{"event_id": "e-cle", "market": "spread", "side": "home", "line": -1.5,
                                              "game": "Tampa Bay Rays @ Cleveland Guardians", "start_utc": "2026-10-19T23:10:00Z"}])
        out = self.say("What would you bet right now?", fire_fn=lambda: held)
        self.assertEqual(out["cards"], [])

    def test_a_game_that_has_started_is_not_offered(self):
        started = dict(FIRE_WITH_PICK, picks=[dict(FIRE_WITH_PICK["picks"][0], start_utc="2026-10-19T20:00:00Z")])
        self.assertEqual(self.say("What would you bet right now?", fire_fn=lambda: started)["cards"], [])

    def test_a_dog_that_cannot_be_fired_says_so_and_does_not_fall_back_to_a_ticket(self):
        out = self.say("What would you bet right now?", fire_fn=None)
        self.assertIn("can't run my rule on demand", out["answer"])
        self.assertNotIn("Cleveland Guardians to win", out["answer"])        # its open ticket is not an answer to "right now"
        self.assertEqual(out["cards"], [])

    def test_a_board_that_cannot_be_read_is_said_not_hidden(self):
        def broken():
            raise RuntimeError("secret internals")
        out = self.say("What would you bet right now?", fire_fn=broken)
        self.assertIn("cannot read the boards", out["answer"])
        self.assertNotIn("secret internals", out["answer"])

    def test_why_not_for_a_game_ahead_reads_what_the_rule_saw(self):
        out = self.say("why didn't you bet the Commanders", fire_fn=lambda: FIRE_NOTHING)
        self.assertIn("still ahead of me", out["answer"])
        self.assertIn("I pass.", out["answer"])
        self.assertIn("shorter than my band", out["answer"])

    def test_why_not_for_a_game_the_rule_does_take_says_a_ticket_is_coming(self):
        out = self.say("why didn't you bet the Patriots", fire_fn=lambda: FIRE_NOTHING)
        self.assertIn("my rule does take New England Patriots to win at +127", out["answer"])

    def test_why_not_for_a_game_it_did_bet_says_so(self):
        out = self.say("why didn't you bet the Mariners")
        self.assertIn("I did bet that game", out["answer"])

    def test_why_not_for_a_past_game_it_cannot_see_points_to_the_drill(self):
        out = self.say("why didn't you bet the Dodgers", fire_fn=lambda: FIRE_NOTHING, tickets=list(TICKETS))
        self.assertIn("Tell me which game or team", out["answer"])
        out = self.say("why did you skip the Giants", fire_fn=lambda: FIRE_NOTHING)
        self.assertIn("Tell me which game or team", out["answer"])

    def test_the_rules_answer_quotes_the_rule_and_the_hard_cap(self):
        out = self.say("What are your rules?")
        self.assertIn("My rule: I back the underdog", out["answer"])
        self.assertIn("120 minutes before the start", out["answer"])
        self.assertIn("never take a price of -200 or worse", out["answer"])

    def test_improvement_differs_for_the_owner_and_a_stranger(self):
        owner = self.say("how do I make you better", is_owner=True)["answer"]
        stranger = self.say("how do I make you better")["answer"]
        self.assertIn("you can change my rule", owner)
        self.assertIn("backtest", owner.lower())
        self.assertIn("Suggest a change", stranger)
        for text in (owner, stranger):
            self.assertIn("changes me by itself", text) if "by itself" in text else None
            self.assertNotIn("guarantee", text.lower())

    def test_fans_are_counts_with_a_small_sample_note(self):
        out = self.say("what do fans think")
        self.assertIn("9 ratings so far: 7 Good call, 2 Bad call", out["answer"])
        self.assertIn("small sample", out["answer"])
        empty = self.say("what do fans think", feedback={})["answer"]
        self.assertIn("Nobody has rated my tickets yet", empty)

    def test_graded_tips_are_listed_with_their_verdict(self):
        tips = [{"kind": "fan", "label": "HELPED", "line": "A fan told me to widen my band."}]
        out = self.say("what has the coach said about you", tips=tips)
        self.assertIn("1 graded tip about me", out["answer"])
        self.assertIn("HELPED: A fan told me to widen my band.", out["answer"])
        self.assertIn("No graded tip", self.say("any tips for you")["answer"])

    def test_the_intro_names_the_dog_and_its_rule(self):
        out = self.say("who are you")
        self.assertEqual(out["lines"], ["Dog Days \u00b7 Fetch the plus money."])      # one line; the rules live on the Rules tab
        self.assertNotIn("What I do", out["answer"])
        self.assertNotIn("I back the underdog", out["answer"])
        self.assertNotIn("MLB", out["answer"])

    def test_an_unknown_question_lists_what_the_dog_can_answer(self):
        out = self.say("banana smoothie recipe")
        self.assertFalse(out["matched"])
        for needle in ("why i made a bet", "what i bet today", "how i am doing", "best and worst bet",
                       "right now", "why i skipped a game", "my rules", "make me better"):
            self.assertIn(needle, out["answer"].lower())

    def test_follow_ups_never_repeat_the_question_and_use_the_dogs_own_teams(self):
        out = self.say("How are you doing?")
        self.assertLessEqual(len(out["followups"]), 4)
        self.assertNotIn("How are you doing?", out["followups"])
        self.assertTrue(any("Guardians" in s for s in ask.suggestions(context())))

    def test_ticket_keys_match_what_feedback_uses(self):
        self.assertEqual(ask.ticket_key(TICKETS[1]), "2026-10-18|Boston Red Sox to win")


class TheVoice(unittest.TestCase):
    def test_no_answer_makes_a_claim_or_shouts(self):
        for text, _intent in PHRASINGS:
            for fire_fn in (lambda: FIRE_WITH_PICK, lambda: FIRE_NOTHING):
                out = ask.answer(text, context(fire_fn=fire_fn, is_owner=True))
                self.assertIsNone(CLAIMS.search(out["answer"]), (text, out["answer"]))
                self.assertTrue(out["paper_only"])

    def test_answers_are_first_person(self):
        for text in ("What did you bet today?", "How are you doing?", "What are your rules?",
                     "Why did you bet Boston?", "what's your best bet"):
            a = ask.answer(text, context())["answer"]
            self.assertRegex(a, r"\b(I|My|my|I'm)\b", text)

    def test_the_numbers_in_a_record_answer_are_the_pages_numbers(self):
        a = ask.answer("How are you doing?", context())["answer"]
        allowed = {"12", "6", "0.40", "0.4", "2", "3", "5", "1.1", "1.10", "8", "100", "7", "-0.40"}
        found = set(re.findall(r"\d+(?:\.\d+)?", a))
        self.assertTrue(found <= allowed, found - allowed)

    def test_a_house_dog_speaks_with_its_catchphrase_and_its_trigger(self):
        ctx = context(kind="house", name="Chalk Chihuahua", catchphrase="Short legs, short prices.",
                      rule_english="", rule_text="Moneyline. Bet the favourite between -199 and -101.",
                      trigger="a favourite is priced between -101 and -199", spec=None)
        hello = ask.answer("who are you", ctx)["answer"]
        self.assertEqual(hello, "Chalk Chihuahua \u00b7 Short legs, short prices.")
        why = ask.answer("why did you bet Boston", ctx)["answer"]
        self.assertIn("I bet when a favourite is priced between -101 and -199.", why)


class NothingCallsOut(unittest.TestCase):
    def test_the_package_imports_no_model_client_and_makes_no_network_call(self):
        forbidden = re.compile(r"(?m)^\s*(?:import|from)\s+(anthropic|openai|requests|httpx|urllib\.request|"
                               r"http\.client|socket|aiohttp|websockets)\b")
        for path in PACKAGE.glob("*.py"):
            self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    unittest.main()
