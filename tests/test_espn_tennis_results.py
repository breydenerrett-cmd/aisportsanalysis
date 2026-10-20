"""src/providers/espn_tennis_results.py and names.person_score.

Recorded ESPN responses only (tests/fixtures/espn_results/, trimmed from the real 2026-10-19 ATP and WTA
scoreboards and the 2026-06-10 WTA walkover); injected fetchers; no network, no store.
"""
from __future__ import annotations

import json
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.datasvc import names
from src.providers import espn_tennis_results as E
from src.providers import tennis_results as T

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "espn_results"
NOW = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)


def doc(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def match(**over):
    base = dict(tour="atp", tournament="T", espn_event_id="1", match_id="m1", start_utc="2026-10-19T10:00:00Z",
                status="STATUS_FINAL", state="post", player_a="A One", player_b="B Two", winner="a",
                sets=((6, 4), (6, 3)), note="", round_name="Round 1")
    base.update(over)
    return E.TennisMatch(**base)


class SetArithmetic(unittest.TestCase):
    def test_completed_sets(self):
        for games in ((6, 0), (6, 4), (7, 5), (7, 6), (6, 7), (13, 11), (10, 8), (0, 6)):
            self.assertTrue(E.set_completed(*games), games)

    def test_unfinished_sets(self):
        for games in ((0, 0), (3, 1), (5, 4), (6, 5), (6, 6), (5, 3), (1, 0), (4, 4)):
            self.assertFalse(E.set_completed(*games), games)


class TheRealScoreboards(unittest.TestCase):
    """The trimmed real responses: what the parser makes of ESPN's own shapes."""

    def setUp(self):
        self.atp = E.parse_scoreboard(doc("tennis_atp_scoreboard_2026-10-19.json"), "atp")
        self.wta = E.parse_scoreboard(doc("tennis_wta_scoreboard_2026-10-19.json"), "wta")
        self.by_id = {m.match_id: m for m in self.atp + self.wta}

    def test_doubles_are_not_parsed(self):
        # the ATP fixture holds a doubles final and a cancelled doubles match beside nine singles
        self.assertEqual(len(self.atp), 7)
        self.assertEqual(len(self.wta), 9)         # nine singles; the WTA doubles final is dropped
        self.assertTrue(all("/" not in m.player_a and "/" not in m.player_b for m in self.atp + self.wta))

    def test_a_straight_sets_final(self):
        m = self.by_id["185037"]
        self.assertEqual((m.player_a, m.player_b, m.winner, m.sets), ("Federico Cina", "Jaume Munar", "b",
                                                                       ((4, 6), (3, 6))))
        self.assertEqual(E.settlement(m)["state"], E.GRADED)
        self.assertEqual(m.start_utc, "2026-10-19T10:05:00Z")

    def test_a_three_set_final_won_by_the_first_player(self):
        m = self.by_id["184992"]
        self.assertEqual((m.winner, m.sets), ("a", ((7, 6), (4, 6), (6, 3))))

    def test_retirement_after_a_completed_set_goes_to_the_player_who_advanced(self):
        m = self.by_id["187001"]            # Jacquet 7-6(7-1) Mmoh, retired
        self.assertEqual(m.status, "STATUS_RETIRED")
        verdict = E.settlement(m)
        self.assertEqual((verdict["state"], verdict["winner"]), (E.GRADED, "a"))
        self.assertIn("retirement after 1 completed set", verdict["reason"])

    def test_retirement_with_the_second_set_barely_started_still_counts_the_first(self):
        m = self.by_id["186942"]            # 6-0 and a retirement: a set was completed
        self.assertEqual(E.settlement(m)["state"], E.GRADED)
        self.assertEqual(E.settlement(m)["winner"], "b")          # Emerson Jones

    def test_retirement_before_a_set_completes_is_void(self):
        for match_id in ("186937", "186962"):                # 3-1 and 5-3 in the first set
            verdict = E.settlement(self.by_id[match_id])
            self.assertEqual((verdict["state"], verdict["winner"]), (E.VOID, None), match_id)
            self.assertIn("retired before a set was completed", verdict["reason"])

    def test_retirement_in_the_second_set_after_one_set_counts(self):
        verdict = E.settlement(self.by_id["185567"])         # McNally 4-6 1-3 Kraus
        self.assertEqual((verdict["state"], verdict["winner"]), (E.GRADED, "b"))

    def test_a_match_in_progress_and_a_scheduled_one_are_pending(self):
        self.assertEqual(E.settlement(self.by_id["185582"])["state"], E.PENDING)
        scheduled = [m for m in self.atp if m.status == "STATUS_SCHEDULED"]
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(E.settlement(scheduled[0])["state"], E.PENDING)

    def test_a_walkover_is_void(self):
        wo = E.parse_scoreboard(doc("tennis_wta_scoreboard_2026-06-10_walkover.json"), "wta")
        walkover = [m for m in wo if m.status == "STATUS_WALKOVER"][0]
        verdict = E.settlement(walkover)
        self.assertEqual((verdict["state"], verdict["winner"]), (E.VOID, None))
        self.assertIn("walkover", verdict["reason"])
        # the same file's retirement after a completed set (Potapova 1-6 0-2 Sonmez) is graded
        retired = [m for m in wo if m.status == "STATUS_RETIRED"][0]
        self.assertEqual(E.settlement(retired)["state"], E.GRADED)


class StatusRules(unittest.TestCase):
    def test_cancelled_and_abandoned_are_void(self):
        for status in ("STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_ABANDONED"):
            self.assertEqual(E.settlement(match(status=status, winner=None))["state"], E.VOID, status)

    def test_postponed_suspended_and_delayed_wait(self):
        for status in ("STATUS_POSTPONED", "STATUS_SUSPENDED", "STATUS_DELAYED", "STATUS_RAIN_DELAY"):
            self.assertEqual(E.settlement(match(status=status, winner=None))["state"], E.PENDING, status)

    def test_default_and_disqualification_follow_the_retirement_rule(self):
        for status in ("STATUS_DEFAULT", "STATUS_DISQUALIFIED"):
            self.assertEqual(E.settlement(match(status=status, sets=((6, 2),)))["state"], E.GRADED, status)
            self.assertEqual(E.settlement(match(status=status, sets=((2, 1),)))["state"], E.VOID, status)

    def test_a_final_without_a_single_winner_is_unresolved_not_graded(self):
        self.assertEqual(E.settlement(match(winner=None))["state"], E.UNRESOLVED)

    def test_a_retirement_without_a_winner_is_unresolved(self):
        self.assertEqual(E.settlement(match(status="STATUS_RETIRED", winner=None))["state"], E.UNRESOLVED)

    def test_an_unknown_status_is_unresolved(self):
        self.assertEqual(E.settlement(match(status="STATUS_SOMETHING_NEW"))["state"], E.UNRESOLVED)

    def test_two_winner_flags_is_no_winner(self):
        bad = doc("tennis_atp_scoreboard_2026-10-19.json")
        comp = bad["events"][0]["groupings"][0]["competitions"][0]
        for competitor in comp["competitors"]:
            competitor["winner"] = True
        parsed = E.parse_scoreboard(bad, "atp")
        self.assertIsNone([m for m in parsed if m.match_id == comp["id"]][0].winner)

    def test_garbage_documents_parse_to_nothing(self):
        for junk in (None, [], "x", {}, {"events": "no"}, {"events": [None, {"groupings": [None]}]}):
            self.assertEqual(E.parse_scoreboard(junk, "atp"), [])


class TheFeed(unittest.TestCase):
    def feed(self, responses=None, **kw):
        calls = []
        served = responses or {"atp": "tennis_atp_scoreboard_2026-10-19.json",
                               "wta": "tennis_wta_scoreboard_2026-10-19.json"}

        def get_json(url):
            calls.append(url)
            tour = url.split("/tennis/")[1].split("/")[0]
            return doc(served[tour])

        sleeps = []
        return E.EspnTennisFeed(get_json=get_json, sleep=sleeps.append, now=lambda: NOW, **kw), calls, sleeps

    def test_it_is_a_results_feed_that_asks_both_tours_for_one_date(self):
        feed, calls, sleeps = self.feed()
        self.assertIsInstance(feed, T.ResultsFeed)
        feed.fetch_results("2026-10-19")
        self.assertEqual(calls, [
            "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard?dates=20261019",
            "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard?dates=20261019"])
        self.assertEqual(sleeps, [E.POLITE_DELAY_SECONDS])        # one pause between the two requests, none first

    def test_results_are_the_settled_matches_scheduled_that_day(self):
        feed, _calls, _sleeps = self.feed()
        rows = feed.fetch_results("2026-10-19")
        # 6 ATP singles (5 final + 1 retired 7-6) and 8 WTA settled singles scheduled on the 19th
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["start_utc"].startswith("2026-10-19"))
            self.assertIn(row["outcome"], ("win", "void"))
        ids = {r["espn_match_id"] for r in rows}
        self.assertIn("185037", ids)
        self.assertNotIn("186937", ids)              # scheduled on the 17th
        self.assertNotIn("185582", ids)              # still in progress

    def test_rows_carry_completed_utc_as_the_moment_it_was_observed(self):
        feed, _c, _s = self.feed()
        row = [r for r in feed.fetch_results("2026-10-19") if r["espn_match_id"] == "185037"][0]
        self.assertEqual(row["completed_utc"], "2026-10-20T06:00:00Z")
        self.assertEqual(row["completed_utc_basis"], "observed")
        self.assertEqual((row["winner"], row["outcome"], row["source"]), ("b", "win", "espn"))
        self.assertEqual(row["player_a"], "Federico Cina")

    def test_a_void_row_has_no_winner_and_names_its_reason(self):
        feed, _c, _s = self.feed()
        rows = feed.fetch_results("2026-10-19")
        void = [r for r in rows if r["outcome"] == "void"]
        self.assertEqual(void, [])                       # no void match was scheduled that day in this slice
        rows_17 = self.feed()[0].fetch_results("2026-10-17")
        void = [r for r in rows_17 if r["outcome"] == "void"]
        self.assertEqual([r["espn_match_id"] for r in void], ["186937"])
        self.assertIsNone(void[0]["winner"])
        self.assertIn("retired before a set was completed", void[0]["void_reason"])

    def test_match_winner_reads_a_void_row_as_no_winner_not_side_b(self):
        row = {"winner": None, "player_a": "A One", "player_b": "B Two"}
        self.assertIsNone(T.match_winner(row, "A One", "B Two"))
        self.assertEqual(T.match_winner({"winner": "b", "player_a": "A One", "player_b": "B Two"}, "A One", "B Two"),
                         "away")

    def test_the_provider_name_espn_builds_this_feed(self):
        self.assertIsInstance(T.feed({"TENNIS_RESULTS_PROVIDER": "espn"}), E.EspnTennisFeed)
        with self.assertRaises(T.TennisResultsError):
            T.feed({"TENNIS_RESULTS_PROVIDER": "nonsense"})
        self.assertIsInstance(T.feed({}), T.NoFeed)            # the default is unchanged

    def test_a_non_json_answer_stops_the_run_and_is_never_worked_around(self):
        class Page:
            def read(self):
                return b"<html>Just a moment...</html>"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=Page()):
            with self.assertRaises(E.EspnTennisError) as caught:
                E.default_get_json(E.scoreboard_url("atp", "2026-10-19"))
        self.assertIn("browser check", str(caught.exception))

    def test_an_http_error_is_a_tennis_results_error(self):
        err = urllib.error.HTTPError("u", 400, "bad", None, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(T.TennisResultsError):
                E.default_get_json(E.scoreboard_url("atp", "2026-10-19"))

    def test_the_request_is_plain_urllib_with_an_ordinary_user_agent(self):
        seen = {}

        class Page:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=None):
            seen["ua"] = request.get_header("User-agent")
            seen["url"] = request.full_url
            return Page()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            E.default_get_json(E.scoreboard_url("wta", "2026-10-19"))
        self.assertTrue(seen["ua"].startswith("Mozilla/5.0"))
        self.assertTrue(seen["url"].endswith("/tennis/wta/scoreboard?dates=20261019"))


class PersonScore(unittest.TestCase):
    """names.person_score: the strict same-person test the result matcher stands on."""

    def test_the_same_name_with_accents_case_and_punctuation_folded(self):
        for a, b in (("Iga Swiatek", "Iga Świątek"), ("Novak Djokovic", "novak  djokovic"),
                     ("Felix Auger-Aliassime", "Felix Auger Aliassime"), ("Botic van de Zandschulp", "Botic Van De Zandschulp"),
                     ("Jan-Lennard Struff", "Jan Lennard Struff"), ("Christopher O'Connell", "Christopher OConnell"),
                     ("Jiri Lehecka", "Jiří Lehečka"), ("Magda Linette", "Magda Linette")):
            self.assertEqual(names.person_score(a, b), names.PERSON_EXACT, (a, b))

    def test_reversed_order(self):
        self.assertEqual(names.person_score("Sinner Jannik", "Jannik Sinner"), names.PERSON_REVERSED)
        self.assertEqual(names.person_score("Aryna Sabalenka", "Sabalenka Aryna"), names.PERSON_REVERSED)

    def test_initials(self):
        for a, b in (("J. Sinner", "Jannik Sinner"), ("Sinner J.", "Jannik Sinner"), ("A. de Minaur", "Alex de Minaur"),
                     ("Jannik Sinner", "J Sinner")):
            self.assertEqual(names.person_score(a, b), names.PERSON_INITIALS, (a, b))

    def test_a_dropped_middle_name_or_particle(self):
        self.assertEqual(names.person_score("Alex Minaur", "Alex de Minaur"), names.PERSON_DROPPED)
        self.assertEqual(names.person_score("Joel Schwaerzler", "Joel Josef Schwaerzler"), names.PERSON_DROPPED)

    def test_other_people_never_match(self):
        for a, b in (("Mischa Zverev", "Alexander Zverev"), ("Venus Williams", "Serena Williams"),
                     ("Alex Zverev", "Alexander Zverev"),            # a nickname is NOT guessed
                     ("A. Zverev", "Mischa Zverev"), ("Zverev", "Alexander Zverev"), ("", "Jannik Sinner"),
                     (None, "Jannik Sinner"), ("Jannik Sinner", "Jannik Sinn"), ("Mick Parkin", "Michael Parkin")):
            self.assertEqual(names.person_score(a, b), 0.0, (a, b))

    def test_a_surname_alone_is_never_a_match_for_a_full_name(self):
        self.assertEqual(names.person_score("Sinner", "Jannik Sinner"), 0.0)

    def test_initials_alone_never_decide(self):
        self.assertEqual(names.person_score("J. S.", "Jannik Sinner"), 0.0)
        self.assertEqual(names.person_score("J. Smith", "Jannik Sinner"), 0.0)


if __name__ == "__main__":
    unittest.main()
