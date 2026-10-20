"""Reading a question (src/hounds/interact/ask_intents.py): typos, slang and no punctuation still land.

THE STORY. On 2026-10-19 the owner asked a member dog with no tickets "What bets would yopu have taken today pre
market" and the dog answered "I have not recorded a ticket yet, so there is nothing to say about my bets". The
old first-regex-wins matcher dropped the question on the floor because one word was mistyped. Every phrasing
below is one a person might plausibly type; each must land on the intent a person means.

Pure text, no data store, no FastAPI.
"""

from __future__ import annotations

import unittest

from src.hounds.interact import ask_intents as ai

OWNER_QUESTION = "What bets would yopu have taken today pre market"

# (question, intent). 'fallback' means nothing should win.
PHRASINGS = [
    # picks_earlier_today: hindsight about today's boards at each game's decision time
    (OWNER_QUESTION, "picks_earlier_today"),
    ("what bets would you have taken today pre market", "picks_earlier_today"),
    ("what would you have taken today", "picks_earlier_today"),
    ("what wud u have taken tday", "picks_earlier_today"),
    ("premarket picks", "picks_earlier_today"),
    ("pre-market plays today?", "picks_earlier_today"),
    ("what would you have played this morning", "picks_earlier_today"),
    ("what would you have bet earlier today", "picks_earlier_today"),
    ("wat woulda u picked earlier", "picks_earlier_today"),
    ("what bets would u have made before the games today", "picks_earlier_today"),
    ("if you had bet this morning what would it be", "picks_earlier_today"),
    ("pre game picks for today", "picks_earlier_today"),
    # picks_now
    ("What would you bet right now?", "picks_now"),
    ("what would you bet", "picks_now"),
    ("wat would u bet rn", "picks_now"),
    ("what would you take tonight", "picks_now"),
    ("what would you play today", "picks_now"),
    ("any plays", "picks_now"),
    ("any picks tonight?", "picks_now"),
    ("who do you like", "picks_now"),
    ("who u like tonight", "picks_now"),
    ("give me picks", "picks_now"),
    ("gimme ur picks", "picks_now"),
    ("what's the play", "picks_now"),
    ("whats the play tonight", "picks_now"),
    ("what do you like today", "picks_now"),
    ("what are you thinking", "picks_now"),
    ("fire", "picks_now"),
    ("take them out back", "picks_now"),
    ("anything tonight", "picks_now"),
    ("what's your best bet tonight", "picks_now"),
    ("what you got today", "picks_now"),
    # backtest_window
    ("what would you have done this week", "backtest_window"),
    ("how would you have done last week", "backtest_window"),
    ("what would you have picked in the last 7 days", "backtest_window"),
    ("last 14 days", "backtest_window"),
    ("backtest the last 30 days", "backtest_window"),
    ("what would you have taken yesterday", "backtest_window"),
    ("how wud u have done last weekend", "backtest_window"),
    ("hindsight last month", "backtest_window"),
    ("replay your rules over the past 2 weeks", "backtest_window"),
    ("if you had bet the last 7 days how would you do", "backtest_window"),
    # today: the recorded tickets
    ("What did you bet today?", "today"),
    ("what bets do you have open", "today"),
    ("show me your latest bet", "today"),
    ("what was your last bet", "today"),
    ("What did you bet yesterday?", "today"),
    ("did you place any bets today", "today"),
    ("what are your open tickets", "today"),
    # record
    ("How are you doing?", "record"),
    ("hows it going", "record"),
    ("what's your record", "record"),
    ("whats ur recrod", "record"),
    ("are you any good", "record"),
    ("how many units are you up", "record"),
    ("what's your CLV", "record"),
    ("how did you do this week", "record"),
    ("are you winning", "record"),
    # best_worst
    ("What's your best bet?", "best_worst"),
    ("worst bet?", "best_worst"),
    ("biggest win so far", "best_worst"),
    ("what was your worst loss", "best_worst"),
    # why_bet / why_not
    ("Why did you bet Boston?", "why_bet"),
    ("explain that pick", "why_bet"),
    ("what made you take Cleveland", "why_bet"),
    ("how come you backed the underdog", "why_bet"),
    ("wy did u bet the rays", "why_bet"),
    ("Why didn't you bet the Yankees?", "why_not"),
    ("why did you skip the Rays", "why_not"),
    ("why no bet on the Guardians game", "why_not"),
    ("why not the over tonight", "why_not"),
    # rules
    ("What are your rules?", "rules"),
    ("how do you pick games", "rules"),
    ("explain your strategy", "rules"),
    ("whats ur strategy", "rules"),
    ("what do you bet on", "rules"),
    # how to improve
    ("How do I make you better?", "improve"),
    ("can I train you", "improve"),
    ("how do i improve u", "improve"),
    # explain_market
    ("what is a spread", "explain_market"),
    ("whats a run line", "explain_market"),
    ("what does over under mean", "explain_market"),
    ("explain moneyline", "explain_market"),
    ("what is a prop bet", "explain_market"),
    ("what are units", "explain_market"),
    ("what is a bankroll", "explain_market"),
    ("what's the vig", "explain_market"),
    ("what is clv", "explain_market"),
    ("what does push mean", "explain_market"),
    # fans, coach, help, hello
    ("what do fans think?", "fans"),
    ("any feedback on you", "fans"),
    ("what has the coach said about you", "coach"),
    ("help", "help"),
    ("what can you do", "help"),
    ("what can i ask you", "help"),
    ("menu", "help"),
    ("who are you", "hello"),
    ("hi", "hello"),
    ("yo", "hello"),
    # nothing: the dog answers with the closest thing and the menu
    ("banana smoothie recipe", "fallback"),
    ("what's the weather in Boston", "fallback"),
    ("asdf", "fallback"),
    ("", "fallback"),
]


def intent_of(text: str, protect=()) -> str:
    name, top = ai.best_intent(ai.scores(text, protect))
    return name if name and top >= ai.MIN_SCORE else "fallback"


class TheMatcher(unittest.TestCase):
    def test_there_are_at_least_sixty_phrasings_and_every_intent_is_covered(self):
        self.assertGreaterEqual(len(PHRASINGS), 60)
        covered = {i for _t, i in PHRASINGS}
        self.assertEqual(covered, set(ai.PRIORITY) | {"fallback"})

    def test_every_phrasing_lands_on_its_intent(self):
        wrong = [(text, want, intent_of(text)) for text, want in PHRASINGS if intent_of(text) != want]
        self.assertEqual(wrong, [])

    def test_the_owners_exact_question_is_the_earlier_today_picks(self):
        self.assertEqual(intent_of(OWNER_QUESTION), "picks_earlier_today")


class TheNormalizer(unittest.TestCase):
    def test_the_known_slips_are_fixed_token_by_token(self):
        self.assertEqual(ai.normalize("yopu"), "you")
        self.assertIn("what", ai.normalize("wat").split())
        self.assertIn("would", ai.normalize("wud").split())
        self.assertIn("today", ai.normalize("tday").split())
        self.assertIn("rightnow", ai.normalize("bet rn").split())

    def test_stemming_folds_forms_of_one_word(self):
        self.assertEqual(ai.normalize("betting bets bet"), "bet bet bet")
        self.assertEqual(ai.normalize("taken took takes"), "take take take")
        self.assertEqual(ai.normalize("picks picked"), "pick pick")

    def test_punctuation_case_and_apostrophes_do_not_matter(self):
        for text in ("WHAT'S YOUR RECORD???", "whats  your record", "What’s your record"):
            self.assertEqual(ai.normalize(text), ai.normalize("whats your record"))

    def test_an_unknown_misspelling_of_a_long_word_is_repaired_but_a_name_is_not(self):
        self.assertIn("tonight", ai.normalize("whats the play tonigth").split())
        self.assertIn("record", ai.normalize("whats your recrod").split())
        self.assertIn("astro", ai.normalize("why did you skip the astros").split())     # stemmed, never repaired
        self.assertIn("giant", ai.normalize("why did you skip the giants").split())
        # a protected word is left alone even when it looks like a slip
        self.assertIn("prop", ai.normalize("what about prop", protect=["prop"]).split())

    def test_multi_word_ideas_become_one_marker(self):
        for text, marker in (("pre market", "premarket"), ("pre-market", "premarket"), ("right now", "rightnow"),
                             ("this morning", "earlier"), ("would have", "wouldhave"), ("wouldn't", "would")):
            self.assertIn(marker, ai.normalize(f"x {text} y"), text)


class TheWindow(unittest.TestCase):
    def test_a_window_is_one_of_the_drills_choices(self):
        for text, days, kind in (("what would you have done this week", 7, "thisweek"),
                                 ("last 7 days", 7, "days"), ("last 14 days", 14, "days"),
                                 ("past 30 days", 30, "days"), ("past 10 days", 14, "days"),
                                 ("last month", 30, "month"), ("last week", 7, "week"),
                                 ("yesterday", 7, "yesterday"), ("last weekend", 7, "weekend"),
                                 ("over the last 2 weeks", 14, "days"), ("what would you have done", 7, "default")):
            got = ai.parse_window(text)
            self.assertEqual((got["days"], got["kind"]), (days, kind), text)

    def test_a_window_longer_than_thirty_days_is_clipped_and_says_so(self):
        got = ai.parse_window("last 90 days")
        self.assertEqual((got["days"], got["clipped"]), (30, True))


class TheGlossaryTerm(unittest.TestCase):
    def test_terms_are_found_in_the_normalized_question(self):
        for text, term in (("what is a spread", "spread"), ("what is a run line", "runline"),
                           ("what does over under mean", "total"), ("what are units", "unit"),
                           ("whats the vig", "vig"), ("explain a parlay", "parlay")):
            self.assertEqual(ai.glossary_term(ai.normalize(text)), term, text)
        self.assertIsNone(ai.glossary_term(ai.normalize("who do you like")))


if __name__ == "__main__":
    unittest.main()
