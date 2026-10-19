"""The coach report card's surfaces: the payload, the route (and its place in the mount order), the kennel feed
items, the digest line.

The payload, feed and digest tests need no FastAPI (Linux CI has none); the route tests skip cleanly where it
is missing. Everything is built from a temp ledger: nothing reads the real evidence directory.
"""

from __future__ import annotations

import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import coach_card as C
from src.hounds import coach_grade as G
from src.hounds import coach_report as R
from src.hounds import digest as D
from src.hounds import kennel_feed as K
from tests import _coach_card_fixtures as F

ROOT = Path(__file__).resolve().parents[1]
BANNED = re.compile(r"\block\b|guarantee|can't lose|sure thing|profit|lifetime|get rich", re.IGNORECASE)


def hindsight(units_diff, **kw):
    return dict({"hindsight": True, "status": "ok", "units_diff": units_diff, "window_first": "2026-09-01",
                 "window_last": "2026-10-01", "window_days": 30, "n_paired": 12,
                 "champion": {"bets": 12, "units": -3.0}, "suggested": {"bets": 5, "units": -0.9},
                 "both_bet": {"games": 5, "units_diff": 0.0, "clv_diff": 0.1, "clv_n": 5}}, **kw)


def forward(label, n, units, **kw):
    return dict({"label": label, "n_paired": n, "n_dates": min(n, 6), "units_diff": units, "mean_d": None,
                 "ci_low": None, "ci_high": None, "champion": {"bets": n}, "suggested": {"bets": n},
                 "both_bet": {"games": 0, "units_diff": 0.0, "clv_diff": None, "clv_n": 0}}, **kw)


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = F.paths_in(Path(self._tmp.name))

    def tip(self, issue, *, recorded="2026-10-10T12:00:00Z", hind=None, fwd=None, hound_name="Fake Dog", **kw):
        row = F.suggestion_row(issue=issue, recorded=recorded, hound_name=hound_name, **kw)
        C.append(self.paths, C.K_SUGGESTION, now=C.parse(recorded), **row)
        if hind is not None:
            C.append(self.paths, C.K_HINDSIGHT, now=C.parse(recorded), issue=issue, hound="fake_dog", **hind)
        if fwd is not None:
            C.append(self.paths, C.K_FORWARD, now=C.parse(recorded), issue=issue, hound="fake_dog", **fwd)

    def refuse(self, issue, reason="bad_json", utc="2026-10-10T13:00:00Z"):
        C.append(self.paths, C.K_REFUSED, now=C.parse(utc), issue=issue, issue_url="u", hound=None, reason=reason,
                 message="m")

    def report(self, **kw):
        R._CACHE.clear()
        return R.build(self.paths, **kw)


class ThePayload(Fixture):
    def test_the_one_liner_names_the_dog_the_change_in_the_dogs_words_hindsight_and_the_live_grade(self):
        self.tip(1, hind=hindsight(2.1), fwd=forward("TOO EARLY", 3, 0.5))
        line = self.report()["items"][0]["line"]
        self.assertEqual(line, 'Coach told Fake Dog to change "Smallest home price that gets a bet" from +100 or '
                               "more to +120 or more. Hindsight: +2.1u better. Live: too early (3 bets).")

    def test_hindsight_is_always_labelled_and_a_missing_grade_is_a_sentence_not_a_zero(self):
        self.tip(1)                                                        # nothing graded yet
        item = self.report()["items"][0]
        self.assertIs(item["hindsight"]["hindsight"], True)
        self.assertIsNone(item["hindsight"]["units_diff"])
        self.assertIn("Hindsight: still being worked out.", item["line"])
        self.assertIn("Live: too early (0 bets).", item["line"])
        self.tip(2, hind={"hindsight": True, "status": "error", "error": "KeyError"})
        by = {i["issue"]: i for i in self.report()["items"]}
        self.assertIn("Hindsight: could not be worked out.", by[2]["line"])

    def test_worse_and_level_hindsight_and_the_decided_live_grades_read_plainly(self):
        self.tip(1, hind=hindsight(-1.7), fwd=forward("HURT", 24, -3.4))
        self.tip(2, hind=hindsight(0.0), fwd=forward("HELPED", 30, 4.2))
        self.tip(3, hind=hindsight(0.04), fwd=forward("NO DIFFERENCE", 1, 0.0))
        by = {i["issue"]: i["line"] for i in self.report()["items"]}
        self.assertIn("Hindsight: -1.7u worse. Live: hurt (-3.4u over 24 bets).", by[1])
        self.assertIn("Hindsight: no different (+0.0u). Live: helped (+4.2u over 30 bets).", by[2])
        self.assertIn("Live: no difference (+0.0u over 1 bet).", by[3])

    def test_the_summary_counts_tips_refusals_and_each_live_verdict_and_totals_them_apart(self):
        self.tip(1, hind=hindsight(2.0), fwd=forward("HELPED", 25, 3.0))
        self.tip(2, hind=hindsight(-1.0), fwd=forward("HURT", 22, -2.0))
        self.tip(3, hind=hindsight(0.5), fwd=forward("NO DIFFERENCE", 40, 0.1))
        self.tip(4, hind=hindsight(1.0), fwd=forward("TOO EARLY", 4, 0.4))
        self.tip(5)                                                        # no forward row yet: too early too
        self.refuse(6)
        self.refuse(7, "params_invalid")
        s = self.report()["summary"]
        self.assertEqual((s["suggestions"], s["refused"]), (5, 2))
        self.assertEqual((s["helped"], s["hurt"], s["no_difference"], s["too_early"]), (1, 1, 1, 2))
        self.assertEqual(s["graded_forward"], 3)
        self.assertEqual(s["forward_units_diff"], 1.5)           # 3.0 - 2.0 + 0.1 + 0.4 + 0.0
        self.assertEqual(s["hindsight_units_diff"], 2.5)         # 2.0 - 1.0 + 0.5 + 1.0
        self.assertIn("rehearsal", s["hindsight_note"])

    def test_the_newest_row_per_issue_wins_and_the_list_is_the_last_twenty_newest_first(self):
        for i in range(1, 26):
            self.tip(i, recorded=f"2026-10-{i:02d}T12:00:00Z")
        C.append(self.paths, C.K_FORWARD, now=C.parse("2026-10-26T00:00:00Z"), issue=25, hound="fake_dog",
                 **forward("TOO EARLY", 1, 0.1))
        C.append(self.paths, C.K_FORWARD, now=C.parse("2026-10-27T00:00:00Z"), issue=25, hound="fake_dog",
                 **forward("TOO EARLY", 2, 0.2))
        rep = self.report()
        self.assertEqual(len(rep["items"]), 20)
        self.assertEqual(rep["items"][0]["issue"], 25)
        self.assertEqual(rep["items"][0]["forward"]["n_paired"], 2)
        self.assertEqual(rep["summary"]["suggestions"], 25)               # the summary is not limited to the list

    def test_an_empty_ledger_is_calm_not_a_404_and_invents_no_number(self):
        rep = self.report()
        self.assertIs(rep["computed"], False)
        self.assertEqual(rep["items"], [])
        self.assertEqual(rep["summary"]["suggestions"], 0)
        self.assertIsNone(rep["summary"]["forward_units_diff"])
        self.assertIsNone(rep["summary"]["hindsight_units_diff"])
        self.assertIn("has not made a suggestion yet", rep["message"])
        self.assertIsNone(R.digest_line(rep))

    def test_recent_refusals_are_listed_with_their_reasons(self):
        self.refuse(6, "bad_json")
        self.refuse(8, "too_soon_practice")
        got = self.report()["recent_refused"]
        self.assertEqual([(r["issue"], r["reason"]) for r in got], [(8, "too_soon_practice"), (6, "bad_json")])

    def test_a_tampered_ledger_is_reported_not_trusted(self):
        self.tip(1)
        self.assertIs(self.report()["chain_ok"], True)
        text = self.paths.ledger.read_text(encoding="utf-8").replace("Fake Dog", "Real Dog")
        self.paths.ledger.write_text(text, encoding="utf-8")
        self.assertIs(self.report()["chain_ok"], False)

    def test_paper_only_and_not_advice_ride_on_the_payload(self):
        rep = self.report()
        self.assertIs(rep["paper_only"], True)
        self.assertIn("not advice", rep["not_advice"].lower())

    def test_the_digest_line(self):
        self.tip(1, fwd=forward("HELPED", 25, 3.0))
        self.tip(2, fwd=forward("HURT", 22, -2.0))
        self.tip(3)
        self.assertEqual(R.digest_line(self.report()), "🧠 Coach: 3 tips so far, 1 helped, 1 hurt (live)")


class TheKennelFeed(Fixture):
    def feed(self, **kw):
        events = K.coach_events(self.report(**kw), base_url="https://linehound.app")
        return events, K.render_feed(events, base_url="https://linehound.app")

    def test_a_new_suggestion_is_an_item_with_the_plain_change_and_what_hindsight_says(self):
        self.tip(7, recorded="2026-10-12T09:30:00Z", hind=hindsight(2.1))
        events, xml = self.feed()
        tip = next(e for e in events if e["kind"] == "coach_tip")
        self.assertEqual(tip["title"], '🧠 Coach tip for Fake Dog: "Smallest home price that gets a bet" from +100 '
                                       "or more to +120 or more. Hindsight says +2.1u.")
        self.assertEqual(tip["guid"], "kennel:coach_tip:7")
        self.assertEqual(tip["pub"].isoformat(), "2026-10-12T09:30:00+00:00")        # the tip's own time, not now
        item = ET.fromstring(xml).findall("./channel/item")[0]
        self.assertIn("rehearsal and not proof", item.find("description").text)
        self.assertTrue(item.find("description").text.endswith("Paper bets only, not advice. 21+."))
        self.assertIn("learning.html", item.find("link").text)
        self.assertEqual(item.find("guid").get("isPermaLink"), "false")

    def test_negative_hindsight_is_said_just_as_plainly_and_a_missing_one_is_a_sentence(self):
        self.tip(1, hind=hindsight(-1.4))
        self.tip(2)
        by = {e["guid"]: e["title"] for e in self.feed()[0] if e["kind"] == "coach_tip"}
        self.assertTrue(by["kennel:coach_tip:1"].endswith("Hindsight says -1.4u."))
        self.assertTrue(by["kennel:coach_tip:2"].endswith("Hindsight is still being worked out."))

    def test_the_report_card_item_appears_once_a_day_with_the_counts_and_a_dated_guid(self):
        self.tip(1, recorded="2026-10-12T09:30:00Z", fwd=forward("HELPED", 25, 3.0))
        self.tip(2, recorded="2026-10-12T10:30:00Z", fwd=forward("HURT", 22, -2.0))
        self.tip(3, recorded="2026-10-12T11:30:00Z")
        card = [e for e in self.feed()[0] if e["kind"] == "coach_card"]
        self.assertEqual(len(card), 1)
        self.assertEqual(card[0]["title"], "📋 Coach report card: 3 tips, 1 helped, 1 hurt, 1 too early")
        self.assertEqual(card[0]["guid"], "kennel:coach_card:2026-10-12")
        # another change the same day does not mint a second guid for that day
        C.append(self.paths, C.K_FORWARD, now=C.parse("2026-10-12T20:00:00Z"), issue=3, hound="fake_dog",
                 **forward("TOO EARLY", 2, 0.2))
        card2 = [e for e in self.feed()[0] if e["kind"] == "coach_card"]
        self.assertEqual(card2[0]["guid"], card[0]["guid"])
        # the next day it changes again: a new guid, so the Zap fires once more
        C.append(self.paths, C.K_FORWARD, now=C.parse("2026-10-13T08:00:00Z"), issue=3, hound="fake_dog",
                 **forward("TOO EARLY", 3, 0.3))
        card3 = [e for e in self.feed()[0] if e["kind"] == "coach_card"]
        self.assertEqual(card3[0]["guid"], "kennel:coach_card:2026-10-13")

    def test_two_polls_of_an_unchanged_card_are_byte_identical(self):
        self.tip(1, hind=hindsight(1.0), fwd=forward("TOO EARLY", 3, 0.3))
        self.assertEqual(self.feed()[1], self.feed()[1])

    def test_an_empty_card_adds_nothing(self):
        self.assertEqual(K.coach_events(self.report()), [])
        self.assertEqual(K.coach_events(None), [])

    def test_a_refusal_alone_makes_a_card_item_but_no_tip_item(self):
        self.refuse(5)
        self.assertEqual([e["kind"] for e in self.feed()[0]], ["coach_card"])     # a refusal is a change; no tip yet
        self.tip(6)
        self.assertEqual(sorted(e["kind"] for e in self.feed()[0]), ["coach_card", "coach_tip"])

    def test_the_voice_has_no_lock_or_profit_talk_and_no_mentions(self):
        self.tip(1, hind=hindsight(2.1), fwd=forward("HELPED", 25, 3.0), hound_name="@everyone Dog")
        text = " ".join(e["title"] + " " + e["why"] for e in self.feed()[0])
        self.assertIsNone(BANNED.search(text))
        self.assertNotIn("@", text)

    def test_collect_with_no_seam_reads_the_report_ledger_by_default(self):
        self.tip(1, hind=hindsight(2.1))
        R._CACHE.clear()
        with mock.patch.object(C.Paths, "default", staticmethod(lambda root=None: self.paths)):
            events = K.collect(SimpleNamespace(hounds={}), states={}, user_rows=[])
        self.assertEqual(sorted(e["kind"] for e in events), ["coach_card", "coach_tip"])

    def test_an_unreadable_report_ledger_means_no_coach_items_not_a_broken_feed(self):
        with mock.patch("src.hounds.coach_report.build", side_effect=OSError("disk")):
            self.assertEqual(K.collect(SimpleNamespace(hounds={}), states={}, user_rows=[]), [])

    def test_the_kennel_collect_includes_the_coach_items_through_the_seam(self):
        self.tip(1, hind=hindsight(2.1))
        book = SimpleNamespace(hounds={})
        events = K.collect(book, states={}, user_rows=[], coach=self.report())
        self.assertEqual(sorted(e["kind"] for e in events), ["coach_card", "coach_tip"])


class TheDigestLine(unittest.TestCase):
    def board(self, n=3):
        hounds = [{"id": f"h{i}", "name": f"Dog Number {i}", "category": "stats",
                   "record": {"bets": 20, "wins": 12, "losses": 8, "units_average_price": 2.0},
                   "verdict": {"label": "TOO EARLY"}} for i in range(n)]
        return {"hounds": hounds, "as_of": "2026-10-18T12:00:00Z"}

    def test_the_line_is_in_the_post_after_the_verdict_and_before_the_footer(self):
        post = D.build_post(self.board(), None, None, "🧠 Coach: 3 tips so far, 1 helped, 1 hurt (live)")
        lines = post.splitlines()
        i = lines.index("🧠 Coach: 3 tips so far, 1 helped, 1 hurt (live)")
        self.assertTrue(lines[i - 1].startswith("🧠 "))                       # right after the sharp-or-lucky line
        self.assertEqual(lines[-2], D.CLOSING_LINE)

    def test_no_line_without_a_tip(self):
        self.assertNotIn("Coach", D.build_post(self.board(), None, None, None))

    def test_the_post_stays_under_900_characters_and_the_coach_line_is_the_last_to_go(self):
        board = self.board(40)
        graveyard = {"hounds": [{"name": "Very Long Dog Name Indeed " * 2, "retired": {"date": "2026-10-01", "cause": "x " * 60}}]}
        post = D.build_post(board, graveyard, None, "🧠 Coach: 12 tips so far, 3 helped, 2 hurt (live)")
        self.assertLessEqual(len(post), D.MAX_POST_CHARS)
        self.assertIn("🧠 Coach: 12 tips so far", post)

    def test_a_banned_phrase_in_the_line_leaves_it_out_rather_than_printing_it(self):
        post = D.build_post(self.board(), None, None, "Coach has the edge: 3 tips")
        self.assertNotIn("edge", post.lower().replace("knowledge", ""))

    def test_the_digest_payload_carries_it(self):
        body = D.digest(self.board(), None, None, "🧠 Coach: 1 tip so far, 0 helped, 0 hurt (live)")
        self.assertIn("1 tip so far", body["post"])
        self.assertIs(body["skip"], False)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRoute(Fixture):
    def client(self):
        import api.app as app_mod
        from fastapi.testclient import TestClient
        return TestClient(app_mod.app)

    def test_the_route_serves_the_report_and_is_not_read_as_a_hound_id(self):
        self.tip(1, hind=hindsight(2.1), fwd=forward("TOO EARLY", 3, 0.5))
        R._CACHE.clear()
        with mock.patch.object(C.Paths, "default", staticmethod(lambda root=None: self.paths)):
            r = self.client().get("/hounds/coach/report")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["summary"]["suggestions"], 1)
        self.assertEqual(len(body["items"]), 1)
        self.assertIn("Hindsight: +2.1u better. Live: too early (3 bets).", body["items"][0]["line"])
        self.assertIn("max-age", r.headers["cache-control"])
        self.assertNotIn("no such hound", r.text)

    def test_with_no_ledger_it_is_a_calm_200(self):
        R._CACHE.clear()
        with mock.patch.object(C.Paths, "default", staticmethod(lambda root=None: self.paths)):
            r = self.client().get("/hounds/coach/report")
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.json()["computed"], False)

    def test_the_digest_route_helper_reads_the_card_and_never_raises(self):
        import api.hounds as hounds_api
        self.tip(1, fwd=forward("HELPED", 25, 3.0))
        R._CACHE.clear()
        with mock.patch.object(C.Paths, "default", staticmethod(lambda root=None: self.paths)):
            self.assertEqual(hounds_api._coach_digest_line(), "🧠 Coach: 1 tip so far, 1 helped, 0 hurt (live)")
        with mock.patch("src.hounds.coach_report.build", side_effect=RuntimeError("unreadable")):
            self.assertIsNone(hounds_api._coach_digest_line())


class MountOrder(unittest.TestCase):
    def test_the_report_route_is_registered_before_the_hound_id_catch_all(self):
        """The router that owns /hounds/coach/report is included BEFORE api.hounds (which has GET /hounds/{id})."""
        text = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        learning = text.index("app.include_router(hounds_learning_router)")
        catchall = text.index("app.include_router(hounds_router)")
        self.assertLess(learning, catchall)
        src = (ROOT / "api" / "hounds_learning.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/hounds/coach/report")', src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
