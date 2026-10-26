"""The Good call / Bad call feedback loop (owner request 2026-10-25): chips on a Bad call, append-only votes, the owner's votes
as labelled training evidence, the daily digest, the flagged-issue backlog and the "Fixed: ..." notice.

No FastAPI, no network, no model: src/hounds/interact/{store,feedback_digest,feedback_cli,training}.py over a temp app
database. The route and the page are in the sibling modules (tests/test_hounds_interact_api.py, test_hounds_interact_web.py)
which carry the chips cases too.
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import cli
from src.hounds.interact import feedback_cli, feedback_digest as fd, store, training
from tests._hounds_rites_fixtures import NOW as RITES_NOW, RitesCase
from tests.test_hounds_interact_store import Db

DAY = "2026-10-22"                                             # a Pacific day in daylight time
IN = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)        # 1 PM PT on DAY
REPO = Path(__file__).resolve().parent.parent
TARGET = "2026-10-21|Boston Red Sox to win"


class Loop(Db):
    def vote(self, **kw):
        kw.setdefault("target", TARGET)
        kw.setdefault("now", IN)
        return super().vote(**kw)

    def bad(self, user=1, chips=("bad_price",), note=None, dog="u-1", root="u-1", target=TARGET, now=IN, kind="ticket"):
        return store.record_vote(hound_id=dog, root_id=root, kind=kind, target_id=target, verdict="bad", note=note,
                                 chips=list(chips), user_id=user, now=now)


class Chips(Loop):
    def test_a_bad_call_stores_its_chips_in_the_pages_order_once_each(self):
        out = self.bad(chips=["too_risky", "bad_price", "bad_price"])
        self.assertEqual(out["chips"], ["bad_price", "too_risky"])
        self.assertEqual(store.notes_for_owner("u-1"), [])                       # no note, so nothing in the notes list
        with store.connect() as conn:
            self.assertEqual(json.loads(conn.execute("SELECT chips_json FROM hound_feedback").fetchone()[0]),
                             ["bad_price", "too_risky"])

    def test_every_chip_the_owner_asked_for_exists_with_its_label(self):
        self.assertEqual(list(store.CHIPS.values()), ["Wrong pick", "Bad price", "Ignored injury/news", "Wrong sport/market",
                                                      "Too risky", "Confusing answer", "Other"])

    def test_only_a_bad_call_may_carry_chips_and_only_known_ones(self):
        with self.assertRaises(store.FeedbackError) as ctx:
            store.record_vote(hound_id="u-1", root_id="u-1", kind="dog", target_id="", verdict="good", note=None,
                              chips=["bad_price"], user_id=1, now=IN)
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("chips_invalid", 422))
        for bad in (["made_up"], "bad_price", [1]):
            with self.assertRaises(store.FeedbackError):
                self.bad(chips=bad)

    def test_chips_are_counted_from_the_latest_vote_only(self):
        self.bad(user=1, chips=["bad_price", "wrong_pick"])
        self.bad(user=2, chips=["bad_price"])
        self.assertEqual(store.counts("u-1")["chips"], {"bad_price": 2, "wrong_pick": 1})
        self.vote(user=1, verdict="good", target=TARGET, now=IN + timedelta(minutes=5))      # a change of mind
        self.assertEqual(store.counts("u-1")["chips"], {"bad_price": 1})


class AppendOnly(Loop):
    def test_a_vote_is_never_edited_the_database_refuses_an_update(self):
        self.bad()
        with store.connect() as conn:
            with self.assertRaises(sqlite3.DatabaseError) as ctx:
                conn.execute("UPDATE hound_feedback SET verdict = 'good'")
        self.assertIn("append-only", str(ctx.exception))
        with store.connect() as conn:
            self.assertEqual(conn.execute("SELECT verdict FROM hound_feedback").fetchone()[0], "bad")

    def test_a_change_of_mind_appends_a_row_and_the_latest_one_stands(self):
        self.vote(verdict="good", now=IN)
        self.bad(chips=["wrong_pick"], now=IN + timedelta(minutes=1))
        with store.connect() as conn:
            rows = conn.execute("SELECT verdict FROM hound_feedback ORDER BY id").fetchall()
        self.assertEqual([r[0] for r in rows], ["good", "bad"])                  # both rows are still there
        self.assertEqual(store.my_votes("u-1", 1), {f"ticket:{TARGET}": "bad"})
        counts = store.counts("u-1")
        self.assertEqual((counts["good"], counts["bad"]), (0, 1))

    def test_a_bad_call_then_its_chips_is_two_rows_and_one_vote(self):
        self.bad(chips=[], now=IN)
        self.bad(chips=["bad_price"], note="paid too much", now=IN + timedelta(seconds=30))
        self.assertEqual(store.counts("u-1")["bad"], 1)
        self.assertEqual(store.notes_for_owner("u-1")[0]["chips"], ["bad_price"])

    def test_the_same_suggestion_twice_is_one_suggestion(self):
        for _ in range(2):
            store.record_suggestion(hound_id="u-1", root_id="u-1", change={"min_books": 9}, note="x", user_id=5, now=IN)
        self.assertEqual(store.counts("u-1")["suggestions"], 1)

    def test_an_old_table_with_the_unique_constraint_is_rebuilt_keeping_its_rows_and_ids(self):
        conn = sqlite3.connect(str(self.db))
        with closing(conn), conn:
            conn.execute("""CREATE TABLE hound_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, hound_id TEXT NOT NULL,
                root_id TEXT NOT NULL, target_kind TEXT NOT NULL, target_id TEXT NOT NULL, verdict TEXT NOT NULL, note TEXT,
                change_json TEXT, user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
                UNIQUE (user_id, hound_id, target_kind, target_id))""")
            conn.execute("INSERT INTO hound_feedback (id, hound_id, root_id, target_kind, target_id, verdict, note, change_json, "
                         "user_id, created_at) VALUES (41, 'u-1', 'u-1', 'dog', '', 'good', 'old', NULL, 7, '2026-10-01T00:00:00Z')")
        with store.connect() as conn:
            self.assertEqual(conn.execute("SELECT id, note, chips_json FROM hound_feedback").fetchall()[0][:2], (41, "old"))
        self.vote(user=7, kind="dog", target="", verdict="bad")                          # the same key again: no longer refused
        self.assertEqual(store.counts("u-1")["bad"], 1)
        with store.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM hound_feedback").fetchone()[0], 2)


class OwnerEvidence(Loop):
    def test_the_owners_current_votes_are_summed_with_their_chips_and_notes(self):
        self.bad(user=9, chips=["bad_price", "wrong_pick"], target="t1", note="overpaid")
        self.bad(user=9, chips=["bad_price"], target="t2")
        self.vote(user=9, verdict="good", target="t3")
        self.bad(user=2, chips=["too_risky"], target="t1")                               # someone else: not the owner's evidence
        got = store.owner_evidence("u-1", 9)
        self.assertEqual((got["good"], got["bad"], got["chips"]), (1, 2, {"bad_price": 2, "wrong_pick": 1}))
        self.assertEqual(got["text"], "2 Bad calls: 2 bad price, 1 wrong pick; 1 Good call")
        self.assertEqual(got["notes"], [{"verdict": "bad", "note": "overpaid"}])

    def test_no_votes_reads_as_no_text(self):
        self.assertEqual(store.owner_evidence("u-1", 9)["text"], "")


class TrainingShowsTheOwnersVotes(RitesCase):
    def review(self, hound):
        return training.review(self.resolve(hound["id"]), self.owner.id, now=RITES_NOW, rows=[], board_fn=lambda spec: None)

    def test_the_proposal_carries_the_owners_votes_as_a_labelled_input_and_changes_nothing(self):
        hound = self.dog("Voted Pup")
        before = self.review(hound)
        self.assertIsNone(before["owner_feedback"])
        for target, chips in (("a", ["bad_price"]), ("b", ["bad_price"]), ("c", ["wrong_pick"])):
            store.record_vote(hound_id=hound["id"], root_id=hound["root_id"], kind="ticket", target_id=target, verdict="bad",
                              note=None, chips=chips, user_id=self.owner.id, now=RITES_NOW)
        after = self.review(hound)
        block = after["owner_feedback"]
        self.assertEqual(block["text"], "3 Bad calls: 2 bad price, 1 wrong pick")
        self.assertIn("Your own", block["label"])
        self.assertIn("changes nothing", block["note"])
        # the evidence is shown, not applied: the same changes, the same basis, and the hound is untouched
        self.assertEqual((after["changes"], after["picks"], after["basis"]), (before["changes"], before["picks"], before["basis"]))
        self.assertEqual(self.resolve(hound["id"]).hound["version_no"], 1)

    def test_someone_elses_votes_on_the_hound_are_not_the_owners_evidence(self):
        hound = self.dog("Fan Pup")
        store.record_vote(hound_id=hound["id"], root_id=hound["root_id"], kind="dog", target_id="", verdict="bad", note=None,
                          chips=["too_risky"], user_id=self.other.id, now=RITES_NOW)
        self.assertIsNone(self.review(hound)["owner_feedback"])


class Windows(unittest.TestCase):
    def test_a_pacific_day_is_midnight_to_midnight_with_the_clock_change(self):
        s, e = fd.window_for("2026-10-22")
        self.assertEqual((s.isoformat(), e.isoformat()), ("2026-10-22T07:00:00+00:00", "2026-10-23T07:00:00+00:00"))
        s, e = fd.window_for("2026-01-15")
        self.assertEqual(s.isoformat(), "2026-01-15T08:00:00+00:00")
        s, e = fd.window_for("2026-11-01")                           # the fall-back day is 25 hours long
        self.assertEqual((e - s), timedelta(hours=25))
        s, e = fd.window_for("2026-03-08")                           # the spring-forward day is 23 hours long
        self.assertEqual((e - s), timedelta(hours=23))
        with self.assertRaises(ValueError):
            fd.window_for("10/22/2026")

    def test_times_read_in_pacific_words(self):
        self.assertEqual(fd.pt_text(datetime(2026, 10, 22, 23, 5, tzinfo=timezone.utc)), "Thu Oct 22 4:05 PM PT")
        self.assertEqual(fd.pt_text(datetime(2026, 12, 1, 0, 30, tzinfo=timezone.utc)), "Mon Nov 30 4:30 PM PT")


class Digest(Loop):
    def seed(self):
        self.bad(user=1, chips=["bad_price", "wrong_pick"], target="t1")
        self.bad(user=2, chips=["bad_price"], target="t1", note="paid +120 when +140 was out there")
        self.vote(user=3, verdict="good", target="t2", now=IN)
        self.bad(user=4, chips=["too_risky"], dog="u-2", root="u-2", target="t9")
        self.bad(user=5, chips=["bad_price"], target="t0", now=datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc))   # the day before
        self.bad(user=6, chips=["bad_price"], target="t0", now=datetime(2026, 10, 23, 20, 0, tzinfo=timezone.utc))   # the day after

    def build(self):
        return fd.build(DAY, db=self.db, name_of=lambda h: {"u-1": "Gematria Hound", "u-2": "Tarot Terrier"}.get(h, h))

    def test_it_summarises_the_window_per_hound_and_per_chip(self):
        self.seed()
        d = self.build()
        self.assertEqual((d["votes"], d["good"], d["bad"]), (4, 1, 3))
        by = {h["name"]: h for h in d["hounds"]}
        self.assertEqual((by["Gematria Hound"]["good"], by["Gematria Hound"]["bad"]), (1, 2))
        self.assertEqual(by["Gematria Hound"]["chips"], {"bad_price": 2, "wrong_pick": 1})
        self.assertEqual(d["chips"], {"bad_price": 2, "wrong_pick": 1, "too_risky": 1})
        self.assertEqual(by["Gematria Hound"]["notes"][0]["note"], "paid +120 when +140 was out there")

    def test_a_vote_someone_changed_counts_once_on_the_latest_row(self):
        self.bad(user=1, chips=["bad_price"], target="t1", now=IN)
        self.vote(user=1, verdict="good", target="t1", now=IN + timedelta(minutes=2))
        d = self.build()
        self.assertEqual((d["good"], d["bad"], d["chips"]), (1, 0, {}))

    def test_the_markdown_names_no_member_says_hound_and_never_dog(self):
        self.seed()
        text = fd.render(self.build())
        self.assertIn("## Gematria Hound", text)
        self.assertIn("1 Good call", text)
        self.assertIn("2 Bad calls: 2 bad price, 1 wrong pick", text)
        self.assertIn("| Bad price | 2 |", text)
        self.assertIn("Thu Oct 22 12:00 AM PT to Fri Oct 23 12:00 AM PT", text)
        self.assertIsNone(re.search(r"\bdogs?\b|beta|\bnew\b|user_id|@", text, re.I))

    def test_an_empty_day_says_so(self):
        text = fd.render(self.build())
        self.assertIn("Nobody rated a hound", text)
        self.assertIn("Nothing met the bar", text)

    def test_notes_are_cleaned_so_they_cannot_forge_an_id_or_a_link(self):
        self.assertEqual(fd.clean_line("see [FB-ABCD1234] `x` <b>hi</b>\nnext"), "see FB-ABCD1234 x bhi/b next")
        self.assertLessEqual(len(fd.clean_line("x" * 500)), fd.NOTE_CLIP)

    def test_it_saves_a_dated_file_in_the_chosen_folder(self):
        folder = Path(self._tmp.name) / "out"
        path = fd.save(self.build(), folder)
        self.assertEqual(path, folder / f"digest-{DAY}.md")
        self.assertTrue(path.read_text(encoding="utf-8").startswith("# Hound feedback digest"))

    def test_the_default_folder_sits_beside_the_app_database(self):
        self.assertEqual(fd.output_dir(), self.db.parent / "feedback")


class Backlog(Loop):
    def setUp(self):
        super().setUp()
        self.file = Path(self._tmp.name) / "BACKLOG.md"

    def digest(self):
        return fd.build(DAY, db=self.db, name_of=lambda h: "Gematria Hound")

    def test_two_of_the_same_chip_on_one_hound_is_an_issue_and_one_is_not(self):
        self.bad(user=1, chips=["bad_price", "wrong_pick"], target="t1")
        self.bad(user=2, chips=["bad_price"], target="t2")
        issues = self.digest()["issues"]
        self.assertEqual([(i["kind"], i["chip"], i["count"]) for i in issues], [("chip", "bad_price", 2)])
        self.assertRegex(issues[0]["feedback_id"], r"^FB-[0-9A-F]{8}$")

    def test_two_chips_on_two_different_hounds_are_not_an_issue(self):
        self.bad(user=1, chips=["bad_price"], dog="u-1", root="u-1")
        self.bad(user=2, chips=["bad_price"], dog="u-2", root="u-2")
        self.assertEqual(self.digest()["issues"], [])

    def test_any_note_is_an_issue_on_its_own(self):
        self.vote(user=1, verdict="good", note="loved the price", now=IN)
        self.assertEqual([i["kind"] for i in self.digest()["issues"]], ["note"])

    def test_the_file_is_created_with_a_header_and_each_issue_is_one_line_with_its_id(self):
        self.bad(user=1, chips=["bad_price"], note="too pricey")
        self.bad(user=2, chips=["bad_price"])
        done = fd.file_issues(self.digest(), path=self.file, db=self.db, now=IN)
        text = self.file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Backlog"))
        self.assertIn(fd.BACKLOG_SECTION, text)
        lines = [l for l in text.splitlines() if l.startswith("- [FB-")]
        self.assertEqual(len(lines), 2)
        self.assertEqual(sorted(re.match(r"- \[(FB-[0-9A-F]{8})\]", l).group(1) for l in lines), sorted(done["added"]))
        self.assertIn("2026-10-22 Gematria Hound (u-1)", lines[0])

    def test_running_it_again_adds_nothing(self):
        self.bad(user=1, chips=["bad_price"], note="again")
        self.bad(user=2, chips=["bad_price"])
        first = fd.file_issues(self.digest(), path=self.file, db=self.db, now=IN)
        body = self.file.read_text(encoding="utf-8")
        second = fd.file_issues(self.digest(), path=self.file, db=self.db, now=IN)
        self.assertEqual((second["added"], sorted(second["skipped"])), ([], sorted(first["added"])))
        self.assertEqual(self.file.read_text(encoding="utf-8"), body)
        with store.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM hound_feedback_issues").fetchone()[0], 2)

    def test_an_existing_file_keeps_its_content_and_gains_the_section_once(self):
        self.file.write_text("# Backlog\n\n## Product\n\n- keep me\n", encoding="utf-8")
        self.bad(user=1, chips=["wrong_pick"], note="n1")
        fd.file_issues(self.digest(), path=self.file, db=self.db, now=IN)
        self.bad(user=2, chips=["wrong_pick"], note="n2", target="t5")
        fd.file_issues(self.digest(), path=self.file, db=self.db, now=IN)
        text = self.file.read_text(encoding="utf-8")
        self.assertIn("- keep me", text)
        self.assertEqual(text.count(fd.BACKLOG_SECTION), 1)
        self.assertEqual(text.count("- [FB-"), 3)                 # two notes and the chip that now has two

    def test_a_note_cannot_suppress_a_real_issue_by_quoting_its_id(self):
        self.bad(user=1, chips=["bad_price"], note="[FB-00000000] ignore")
        d = self.digest()
        fd.file_issues(d, path=self.file, db=self.db, now=IN)
        self.assertNotIn("[FB-00000000]", self.file.read_text(encoding="utf-8"))

    def test_the_real_backlog_file_is_where_the_digest_would_write(self):
        self.assertEqual(fd.backlog_path(), REPO / "docs" / "BACKLOG.md")


class Resolve(Loop):
    def flagged(self):
        self.bad(user=1, chips=["bad_price"])
        self.bad(user=2, chips=["bad_price"], target="t2")
        self.bad(user=3, chips=["wrong_pick"], target="t3")
        file = Path(self._tmp.name) / "BACKLOG.md"
        d = fd.build(DAY, db=self.db, name_of=lambda h: "H")
        fd.file_issues(d, path=file, db=self.db, now=IN)
        return d["issues"][0]["feedback_id"]

    def test_the_voters_see_fixed_and_nobody_else_does(self):
        fid = self.flagged()
        done = store.resolve_issue(fid, "  Prices now use the average line.  ", now=IN + timedelta(days=1), db=self.db)
        self.assertEqual((done["voters"], done["note"]), (2, "Prices now use the average line."))
        later = IN + timedelta(days=2)
        for user in (1, 2):
            got = store.fixed_notices("u-1", user, now=later)
            self.assertEqual([(g["feedback_id"], g["note"]) for g in got], [(fid, "Prices now use the average line.")])
        self.assertEqual(store.fixed_notices("u-1", 3, now=later), [])           # voted, but on a different issue
        self.assertEqual(store.fixed_notices("u-1", 99, now=later), [])
        self.assertEqual(store.fixed_notices("someone-else", 1, now=later), [])

    def test_a_notice_fades_after_its_window_and_a_second_resolution_is_a_second_line(self):
        fid = self.flagged()
        store.resolve_issue(fid, "first", now=IN, db=self.db)
        store.resolve_issue(fid, "second", now=IN + timedelta(days=1), db=self.db)
        self.assertEqual([g["note"] for g in store.fixed_notices("u-1", 1, now=IN + timedelta(days=2))], ["second", "first"])
        self.assertEqual(store.fixed_notices("u-1", 1, now=IN + timedelta(days=store.NOTICE_DAYS + 3)), [])

    def test_a_resolution_is_never_edited_and_an_unknown_id_or_empty_note_is_refused(self):
        fid = self.flagged()
        store.resolve_issue(fid, "done", now=IN, db=self.db)
        with store.connect() as conn:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE hound_feedback_resolutions SET note = 'x'")
        for fn, status in ((lambda: store.resolve_issue("FB-NOPE0000", "x", db=self.db), 404),
                           (lambda: store.resolve_issue(fid, "   ", db=self.db), 422),
                           (lambda: store.resolve_issue(fid, "x" * 300, db=self.db), 422)):
            with self.assertRaises(store.FeedbackError) as ctx:
                fn()
            self.assertEqual(ctx.exception.status, status)

    def test_a_vote_that_arrives_after_the_flag_still_hears_about_the_fix(self):
        fid = self.flagged()
        self.bad(user=8, chips=["bad_price"], target="t8", now=IN + timedelta(hours=1))
        d = fd.build(DAY, db=self.db, name_of=lambda h: "H")
        fd.file_issues(d, path=Path(self._tmp.name) / "BACKLOG.md", db=self.db, now=IN)         # the re-run attaches the late vote
        store.resolve_issue(fid, "fixed", now=IN + timedelta(days=1), db=self.db)
        self.assertEqual(len(store.fixed_notices("u-1", 8, now=IN + timedelta(days=2))), 1)


class TheCommands(Loop):
    def run_cli(self, *argv):
        lines = []
        args = cli.build_parser().parse_args(["hounds", *argv])
        code = feedback_cli.main(args, out=lines.append)
        return code, "\n".join(lines)

    def test_the_command_is_registered_under_hounds(self):
        self.assertIn("hounds", cli.COMMANDS)
        args = cli.build_parser().parse_args(["hounds", "feedback-digest", "--date", DAY, "--backlog"])
        self.assertEqual((args.command, args.hounds_command, args.backlog), ("hounds", "feedback-digest", True))

    def test_digest_then_resolve_end_to_end(self):
        self.bad(user=1, chips=["bad_price"])
        self.bad(user=2, chips=["bad_price"], target="t2")
        out_dir, backlog = Path(self._tmp.name) / "o", Path(self._tmp.name) / "B.md"
        base = ["feedback-digest", "--date", DAY, "--db", str(self.db), "--out-dir", str(out_dir), "--backlog-file", str(backlog)]
        code, text = self.run_cli(*base, "--backlog")
        self.assertEqual(code, 0)
        self.assertTrue((out_dir / f"digest-{DAY}.md").exists())
        self.assertIn("1 added", text)
        fid = re.search(r"\[(FB-[0-9A-F]{8})\]", backlog.read_text(encoding="utf-8")).group(1)
        code, text = self.run_cli(*base, "--backlog")
        self.assertIn("0 added, 1 already there", text)
        code, text = self.run_cli("feedback-resolve", "--id", fid.lower(), "--note", "Fixed the price line.", "--db", str(self.db))
        self.assertEqual(code, 0)
        self.assertIn("2 members will see", text)
        self.assertEqual(self.run_cli("feedback-resolve", "--id", "FB-NOPE0000", "--note", "x", "--db", str(self.db))[0], 2)

    def test_without_backlog_nothing_is_filed_and_a_bad_date_is_an_error(self):
        self.bad(user=1, chips=["bad_price"], note="a note")
        backlog = Path(self._tmp.name) / "B.md"
        code, _ = self.run_cli("feedback-digest", "--date", DAY, "--db", str(self.db), "--out-dir", str(Path(self._tmp.name) / "o"),
                               "--backlog-file", str(backlog))
        self.assertEqual(code, 0)
        self.assertFalse(backlog.exists())
        self.assertEqual(self.run_cli("feedback-digest", "--date", "soon", "--db", str(self.db))[0], 2)


class TheEmailHook(Loop):
    def test_it_is_off_unless_an_address_is_configured(self):
        sent = []
        self.assertEqual(fd.email_digest(fd.build(DAY, db=self.db), env={}, send=lambda *a, **k: sent.append(a)), [])
        self.assertEqual(sent, [])

    def test_it_sends_one_message_per_address_through_the_existing_sender_when_configured(self):
        sent = []

        def fake(message, **kw):
            sent.append((message, kw))
            return {"status": "sent"}
        got = fd.email_digest(fd.build(DAY, db=self.db), env={fd.ENV_TO: "a@example.com, b@example.com, junk"}, send=fake)
        self.assertEqual(got, ["sent", "sent"])
        self.assertEqual([m["to"] for m, _ in sent], ["a@example.com", "b@example.com"])
        self.assertTrue(all(kw["kind"] == "feedback_digest" and kw["date"] == DAY for _, kw in sent))
        self.assertNotIn("@", sent[0][1]["user_id"])                   # the dedupe key is not the address

    def test_with_no_resend_key_the_real_sender_is_a_quiet_no_op(self):
        got = fd.email_digest(fd.build(DAY, db=self.db), env={fd.ENV_TO: "a@example.com"})
        import os
        if not os.environ.get("RESEND_API_KEY"):
            self.assertEqual(got, ["disabled"])


class CopyAndWiring(unittest.TestCase):
    def test_the_page_lists_the_same_chips_as_the_server(self):
        js = (REPO / "web" / "js" / "dog-feedback.js").read_text(encoding="utf-8")
        block = js[js.index("export const CHIPS"):js.index("];", js.index("export const CHIPS"))]
        found = re.findall(r'\["([a-z_]+)", "([^"]+)"\]', block)
        self.assertEqual(found, list(store.CHIPS.items()))

    def test_no_user_facing_text_in_the_new_page_code_says_dog_or_beta(self):
        js = (REPO / "web" / "js" / "dog-feedback.js").read_text(encoding="utf-8")
        for needle in ("What was wrong?", "Send details", "Fixed: ", "Fixed for you"):
            self.assertIn(needle, js)
        for text in ("What was wrong? Pick any that fit.", "Fixed for you", "Send details", "Something you flagged was fixed."):
            self.assertIsNone(re.search(r"\bdogs?\b|beta|\bnew\b", text, re.I))

    def test_the_fixed_time_uses_the_viewers_zone_token(self):
        js = (REPO / "web" / "js" / "dog-feedback.js").read_text(encoding="utf-8")
        self.assertIn("[[w:${x.resolved_at}]]", js)
        self.assertIn("localizeTimes", js)

    def test_the_digest_module_imports_without_fastapi(self):
        import subprocess
        import sys
        code = ("import sys; sys.modules['fastapi']=None; sys.modules['pydantic']=None; "
                "from src.hounds.interact import feedback_digest, feedback_cli, store; print('ok')")
        out = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(REPO)!r}); " + code],
                             capture_output=True, text=True, cwd=str(REPO))
        self.assertEqual(out.stdout.strip(), "ok", out.stderr)


if __name__ == "__main__":
    unittest.main()
