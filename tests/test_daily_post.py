"""Tests for scripts/daily_post.py -- the day's honest public post.

Every builder takes its data as arguments, so nothing here reads a ledger.
Only `main()` reads the disk (through `load_inputs`), and the main() tests
replace that one function with canned inputs.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import scripts.daily_post as daily_post  # noqa: E402

DATE = "2026-10-01"
PREV = "2026-09-30"
CLOSING = "No edge is claimed. 21+. Bet responsibly."


def snapshot(wins=16, losses=17, units=-5.05, days=7, post_staked=0, reason=None,
             state="graded", label="Our value card"):
    return {"current": {
        "label": label, "available": True, "grading_state": state, "reason": reason,
        "wins": wins, "losses": losses, "profit_units": units, "days": days,
        "date_span": {"first": "2026-09-22", "last": "2026-09-30"},
        "postseason": {"wins": 2, "losses": 0, "n_staked": post_staked},
    }}


def card(picks=(), fills=(), no_input=None):
    return {"picks": [{"text": t, "price": p} for t, p in picks],
            "fills": [{"text": t, "price": p} for t, p in fills],
            "no_input": no_input}


def graded(text, price, result, units, section="pick"):
    return {"text": text, "price": price, "result": result, "units": units,
            "section": section}


def inputs(**over):
    base = dict(sport_label="MLB", date=DATE, prev_date=PREV,
                card=card(picks=[("Yankees moneyline at -130", -130),
                                 ("Devers Over 0.5 hits at +120", 120)]),
                graded=[graded("Mets moneyline at -120", -120, "WIN", 0.8333),
                        graded("Cubs moneyline at +105", 105, "LOSS", -1.0)],
                snapshot=snapshot())
    base.update(over)
    return base


FIXTURES = {
    "normal": inputs(),
    "no_card": inputs(card=None),
    "empty_card": inputs(card=card()),
    "no_input_card": inputs(card=card(no_input="stale board")),
    "fills_only": inputs(card=card(fills=[("Padres moneyline at -136", -136)])),
    "nothing_graded": inputs(graded=[]),
    "negative": inputs(snapshot=snapshot(wins=3, losses=9, units=-7.31, days=4)),
    "mixed_sections": inputs(graded=[
        graded("Mets moneyline at -120", -120, "WIN", 0.8333),
        graded("Bo Bichette Under 1.5 total bases at -139", -139, "LOSS", -1.0, "fill"),
        graded("Yankees moneyline at -135", -135, "WIN", 0.7407, "postseason")]),
}


class XLengthTest(unittest.TestCase):
    def test_every_fixture_fits_in_280(self):
        for name, data in FIXTURES.items():
            with self.subTest(fixture=name):
                text = daily_post.build_x(**data)
                self.assertLessEqual(len(text), 280)
                self.assertTrue(text.endswith(CLOSING))

    def test_exactly_280_is_allowed(self):
        def build(n):
            # card=None: both candidates are identical, so 280 is a true edge.
            return daily_post.build_x(**inputs(
                card=None, snapshot=snapshot(state="pending", reason="r" * n)))
        pad = 280 - len(build(1)) + 1  # an empty reason falls back to a default
        self.assertGreater(pad, 0)
        self.assertEqual(len(build(pad)), 280)
        with self.assertRaises(daily_post.PostError):
            build(pad + 1)

    def test_long_entry_list_falls_back_to_a_count_not_a_cut(self):
        many = [(f"Team Number {i} moneyline at -130", -130) for i in range(8)]
        text = daily_post.build_x(**inputs(card=card(picks=many)))
        self.assertLessEqual(len(text), 280)
        self.assertIn("Tonight: 8 picks.", text)
        self.assertIn("Full card in the longer post.", text)
        self.assertNotIn("Team Number 0", text)

    def test_a_post_that_cannot_fit_raises(self):
        data = inputs(snapshot=snapshot(state="pending", reason="r" * 400))
        with self.assertRaises(daily_post.PostError) as ctx:
            daily_post.build_x(**data)
        self.assertIn("280", str(ctx.exception))

    def test_main_exits_2_and_prints_nothing_to_stdout_when_it_cannot_fit(self):
        data = inputs(snapshot=snapshot(state="pending", reason="r" * 400))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(daily_post, "load_inputs", return_value=data), \
                redirect_stdout(out), redirect_stderr(err):
            rc = daily_post.main(["--format", "x", "--date", DATE])
        self.assertEqual(rc, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("280", err.getvalue())


class BannedWordTest(unittest.TestCase):
    WORDS = ("edge", "profit", "lock", "guaranteed", "sharp", "winning", "Bet Check")

    def test_no_banned_word_in_any_fixture_either_format(self):
        for name, data in FIXTURES.items():
            for builder in (daily_post.build_x, daily_post.build_long):
                with self.subTest(fixture=name, builder=builder.__name__):
                    text = builder(**data).replace("No edge is claimed.", "")
                    for label, pattern in daily_post.BANNED_PATTERNS:
                        self.assertIsNone(pattern.search(text), (label, text))

    def test_banned_word_in_an_entry_raises_instead_of_printing(self):
        # Fails if the banned-word check is removed from the builders.
        for word in self.WORDS:
            bad = inputs(card=card(picks=[(f"{word} Rockies moneyline at -130", -130)]))
            for builder in (daily_post.build_x, daily_post.build_long):
                with self.subTest(word=word, builder=builder.__name__):
                    with self.assertRaises(daily_post.PostError) as ctx:
                        builder(**bad)
                    self.assertIn("banned", str(ctx.exception))

    def test_banned_word_arriving_through_the_record_reason_raises(self):
        bad = inputs(snapshot=snapshot(state="pending", reason="a real edge here"))
        with self.assertRaises(daily_post.PostError):
            daily_post.build_long(**bad)

    def test_the_exact_no_edge_sentence_is_the_only_allowed_use(self):
        daily_post.check_text("No edge is claimed.")
        with self.assertRaises(daily_post.PostError):
            daily_post.check_text("We found an edge. No edge is claimed.")
        with self.assertRaises(daily_post.PostError):
            daily_post.check_text("No edge is claimed, honestly.")

    def test_main_exits_2_on_a_banned_word(self):
        bad = inputs(card=card(picks=[("Sharp Elbows moneyline at -130", -130)]))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(daily_post, "load_inputs", return_value=bad), \
                redirect_stdout(out), redirect_stderr(err):
            rc = daily_post.main(["--format", "long", "--date", DATE])
        self.assertEqual(rc, 2)
        self.assertEqual(out.getvalue(), "")


class PriceCutoffTest(unittest.TestCase):
    def test_minus_200_and_shorter_never_shown(self):
        data = inputs(card=card(picks=[("Dodgers moneyline at -250", -250),
                                       ("Padres moneyline at -200", -200),
                                       ("Yankees moneyline at -199", -199),
                                       ("Mets moneyline at +110", 110)]))
        for builder in (daily_post.build_x, daily_post.build_long):
            with self.subTest(builder=builder.__name__):
                text = builder(**data)
                self.assertNotIn("-250", text)
                self.assertNotIn("-200)", text.replace("(priced at -200 or shorter)", ""))
                self.assertNotIn("Dodgers", text)
                self.assertNotIn("Padres", text)
                self.assertIn("Yankees moneyline at -199", text) if builder is daily_post.build_long else None
                self.assertIn("2 entries not shown (priced at -200 or shorter).", text)

    def test_hidden_entries_also_hidden_from_yesterdays_graded_list(self):
        data = inputs(graded=[graded("Rams to win at -300", -300, "WIN", 0.3333)])
        text = daily_post.build_long(**data)
        self.assertNotIn("Rams", text)
        self.assertNotIn("-300", text)
        self.assertIn("1 entry not shown (priced at -200 or shorter).", text)
        self.assertNotIn("No counted picks were graded", text)

    def test_hidden_fill_is_counted_not_shown(self):
        data = inputs(card=card(fills=[("Giants moneyline at -240", -240)]))
        text = daily_post.build_long(**data)
        self.assertNotIn("Giants", text)
        self.assertIn("1 entry not shown (priced at -200 or shorter).", text)

    def test_boundaries_agree_with_the_feeds_own_price_rule_when_it_has_one(self):
        import scripts.discord_feed as discord_feed
        rule = getattr(discord_feed, "_is_postable", None)
        if rule is None:
            self.skipTest("discord_feed has no _is_postable")
        for price in (-300, -201, -200, -199, -110, 100, 250):
            with self.subTest(price=price):
                shown, _, _ = daily_post.split_hidden([{"price": price}])
                self.assertEqual(bool(shown), rule({"price": price}))

    def test_split_hidden_boundaries(self):
        shown, hidden, unpriced = daily_post.split_hidden(
            [{"price": -201}, {"price": -200}, {"price": -199}, {"price": 100}, {"price": None}])
        self.assertEqual([e["price"] for e in shown], [-199, 100])
        self.assertEqual((hidden, unpriced), (2, 1))


class FillsAndPostseasonTest(unittest.TestCase):
    def test_fills_are_labelled_and_never_in_the_counted_record(self):
        data = inputs(card=card(picks=[("Yankees moneyline at -130", -130)],
                                fills=[("Padres moneyline at -136", -136)]))
        text = daily_post.build_long(**data)
        self.assertIn("Fills (not counted in the record):", text)
        self.assertIn("- Padres moneyline at -136", text)
        # The record line is the injected one, unchanged.
        self.assertIn("Our value card: 16-17, -5.05u, 7 nights", text)
        x = daily_post.build_x(**data)
        self.assertIn("+1 fill, not counted", x)

    def test_yesterdays_fills_are_tallied_apart_from_counted_picks(self):
        text = daily_post.build_long(**FIXTURES["mixed_sections"])
        self.assertIn("Counted picks: 1-0, +0.83u", text)
        self.assertIn("Fills, not counted: 0-1, -1.00u", text)
        x = daily_post.build_x(**FIXTURES["mixed_sections"])
        self.assertIn("Yesterday (2026-09-30): 1-0, +0.83u.", x)  # picks only

    def test_postseason_entries_are_labelled(self):
        text = daily_post.build_long(**FIXTURES["mixed_sections"])
        self.assertIn("Postseason (postseason, graded, not counted): 1-0, +0.74u", text)
        picks_only = text.split("Fills, not counted")[0]
        self.assertNotIn("Yankees moneyline at -135", picks_only)

    def test_postseason_record_line_uses_the_label(self):
        data = inputs(snapshot=snapshot(post_staked=2))
        text = daily_post.build_long(**data)
        self.assertIn("Postseason: 2-0, postseason, graded, not counted.", text)

    def test_graded_entries_split_by_class_and_skip_withdrawn(self):
        day = {"date": PREV, "graded": [
            {"kind": "game", "team_name": "Mets", "price": -120, "take": True,
             "entry_class": "pick", "result": "WIN", "profit_units": 0.83, "game_type": "R"},
            {"kind": "prop", "player": "Busch", "side": "Over", "line": 0.5,
             "market": "batter_hits", "price": -130, "entry_class": "fill",
             "result": "LOSS", "profit_units": -1.0, "game_type": "R"},
            {"kind": "game", "team_name": "Yankees", "price": -135, "take": False,
             "entry_class": "fill", "result": "WIN", "profit_units": 0.74, "game_type": "F"},
            {"kind": "prop", "player": "Frelick", "side": "Under", "line": 0.5,
             "market": "batter_hits", "price": 120, "entry_class": "pick",
             "result": "WIN", "profit_units": 1.2, "game_type": "R", "withdrawn": True},
        ]}
        rows = daily_post.graded_entries("mlb", day)
        self.assertEqual([r["section"] for r in rows], ["pick", "fill", "postseason"])
        self.assertEqual(rows[0]["text"], "Mets moneyline at -120")
        self.assertEqual(rows[1]["text"], "Busch Over 0.5 hits at -130")

    def test_graded_entries_use_the_injected_postseason_game_pks(self):
        day = {"graded": [{"kind": "game", "team_name": "Mets", "price": -120,
                           "entry_class": "pick", "result": "WIN", "profit_units": 0.8,
                           "game_pk": 77, "game_type": None}]}
        rows = daily_post.graded_entries("mlb", day, frozenset({77}))
        self.assertEqual(rows[0]["section"], "postseason")

    def test_card_entries_never_read_withdrawn_and_keep_rank_order(self):
        frozen = {"picks": [{"kind": "game", "team_name": "Mets", "price": -120, "take": True, "rank": 2}],
                  "prop_picks": [{"kind": "prop", "player": "Devers", "side": "Under", "line": 1.5,
                                  "market": "batter_total_bases", "price": 110, "rank": 1}],
                  "fills": [{"kind": "game", "team_name": "Cubs", "price": -125, "take": False}],
                  "withdrawn": [{"kind": "game", "team_name": "Ghosts", "price": -110}]}
        out = daily_post.card_entries("mlb", frozen)
        self.assertEqual([e["text"] for e in out["picks"]],
                         ["Devers Under 1.5 total bases at +110", "Mets moneyline at -120"])
        self.assertEqual([e["text"] for e in out["fills"]], ["Cubs moneyline at -125"])
        self.assertNotIn("Ghosts", repr(out))
        self.assertIsNone(daily_post.card_entries("mlb", None))


class EmptyStatesTest(unittest.TestCase):
    def test_no_card_says_so_plainly(self):
        text = daily_post.build_long(**FIXTURES["no_card"])
        self.assertIn(f"No card published for {DATE}.", text)
        self.assertNotIn("nothing qualified", text)
        self.assertIn(f"No card published for {DATE}.", daily_post.build_x(**FIXTURES["no_card"]))

    def test_published_but_empty_is_a_different_sentence_from_no_card(self):
        empty = daily_post.build_long(**FIXTURES["empty_card"])
        none = daily_post.build_long(**FIXTURES["no_card"])
        self.assertIn(f"Card published for {DATE}: nothing qualified.", empty)
        self.assertNotIn("No card published", empty)
        self.assertNotIn("nothing qualified", none)
        self.assertNotEqual(empty, none)

    def test_no_usable_input_is_its_own_sentence(self):
        text = daily_post.build_long(**FIXTURES["no_input_card"])
        self.assertIn("No usable odds input", text)
        self.assertNotIn("nothing qualified", text)

    def test_nothing_graded_yesterday_says_so(self):
        text = daily_post.build_long(**FIXTURES["nothing_graded"])
        self.assertIn(f"Nothing was graded for {PREV}.", text)
        self.assertIn("nothing was graded", daily_post.build_x(**FIXTURES["nothing_graded"]))

    def test_fills_only_card_does_not_claim_a_pick(self):
        text = daily_post.build_long(**FIXTURES["fills_only"])
        self.assertIn("no picks qualified", text)
        self.assertIn("- Padres moneyline at -136", text)

    def test_only_fills_graded_is_not_reported_as_nothing_graded(self):
        data = inputs(graded=[graded("Bo Bichette Under 1.5 total bases at -139", -139,
                                     "WIN", 0.7194, "fill")])
        text = daily_post.build_long(**data)
        self.assertIn(f"No counted picks were graded for {PREV}.", text)
        self.assertNotIn("Nothing was graded", text)


class RecordTest(unittest.TestCase):
    def test_negative_record_printed_unchanged(self):
        data = FIXTURES["negative"]
        long_text = daily_post.build_long(**data)
        x_text = daily_post.build_x(**data)
        self.assertIn("Our value card: 3-9, -7.31u, 4 nights", long_text)
        self.assertIn("3-9, -7.31u, 4 nights", x_text)

    def test_ungraded_record_prints_the_cohorts_own_reason(self):
        data = inputs(snapshot=snapshot(state="pending", reason="no graded picks yet"))
        self.assertIn("no graded picks yet", daily_post.build_long(**data))

    def test_closing_line_is_last_and_no_link(self):
        for name, data in FIXTURES.items():
            with self.subTest(fixture=name):
                long_text = daily_post.build_long(**data)
                self.assertEqual(long_text.splitlines()[-1], CLOSING)
                self.assertNotIn("http", long_text.lower())
                self.assertNotIn("http", daily_post.build_x(**data).lower())


class DeterminismTest(unittest.TestCase):
    def test_same_input_same_output(self):
        for name, data in FIXTURES.items():
            with self.subTest(fixture=name):
                self.assertEqual(daily_post.build_x(**data), daily_post.build_x(**data))
                self.assertEqual(daily_post.build_long(**data), daily_post.build_long(**data))

    def test_builders_do_not_mutate_their_input(self):
        import copy
        data = FIXTURES["mixed_sections"]
        before = copy.deepcopy(data)
        daily_post.build_long(**data)
        daily_post.build_x(**data)
        self.assertEqual(data, before)


class MainTest(unittest.TestCase):
    def _run(self, argv, data=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(daily_post, "load_inputs", return_value=data or inputs()), \
                redirect_stdout(out), redirect_stderr(err):
            rc = daily_post.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_x_only_prints_just_the_post(self):
        rc, out, _ = self._run(["--format", "x", "--date", DATE])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), daily_post.build_x(**inputs()))

    def test_both_prints_both_with_a_character_count(self):
        rc, out, _ = self._run(["--format", "both", "--date", DATE])
        self.assertEqual(rc, 0)
        self.assertIn("===== x (", out)
        self.assertIn("/280 characters) =====", out)
        self.assertIn("===== long =====", out)

    def test_rejects_malformed_date_and_unknown_sport(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                daily_post.main(["--date", "not-a-date"])
            with self.assertRaises(SystemExit):
                daily_post.main(["--sport", "ufc"])

    def test_previous_date_rolls_over_month_and_year(self):
        self.assertEqual(daily_post.previous_date("2026-10-01"), "2026-09-30")
        self.assertEqual(daily_post.previous_date("2027-01-01"), "2026-12-31")


if __name__ == "__main__":
    unittest.main()
