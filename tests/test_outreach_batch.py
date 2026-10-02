"""Outreach batch builder: selection, parsed text, guard, and the append-only pipeline log."""
import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

from scripts import outreach_batch as ob

SCRIPTS = """# scripts

## (a) Discord DM

**Variant A, direct trial offer (10 words)**
> Hi [Name], A text. No edge claimed. Okay?

**Variant B, feedback first (10 words)**
> Hi [Name], B text. I'm not claiming an edge. Look at the record page?

**Variant C, permission first (10 words)**
> Hi [Name], C text. Does [Server] allow bots?

Use: Variant B is the safest first touch.

## (b) Reddit feedback post

**Title:** The title. The MLB number is negative.

**Body:**
> I'm the builder.
>
> I am not claiming an edge. The current MLB record is [MLB_RECORD], which is negative.
>
> 1. First question.

Notes: none.

## (c) Reply template for X

> [One specific thing from their post, e.g. "Your point..."]. MLB record is [MLB_RECORD], so negative, no edge claimed.

## (d) Follow-ups
"""

CHANNELS = """# channels
Compliant way (recommendation):
3. No link in the first message (links in cold DMs are spam). Offer to send one.
Compliant way: reply to a specific post with something relevant to it; one reply per account.
Status: Website Promotions ALLOWED. Risk: moderators may move or delete.
No platform rule applies to emailing a creator. Do not use any bulk tool.
"""

RECORD = {"wins": 16, "losses": 17, "profit_units": -5.0463, "days": 6,
          "date_span": {"first": "2026-09-22", "last": "2026-09-27"}}
URL = "https://example.test/record"


def row(kind, name, status="ALLOWED_WITH_CONDITIONS", size="", focus="", first="first line."):
    return {"type": kind, "name": name, "url": f"https://example.test/{name}", "size": size,
            "sport_focus": focus, "why_fit": "", "contact_path": "path", "rule_status": status,
            "first_line": first, "checked": "2026-10-01"}


def names(rows):
    return [r["name"] for r in rows]


def many_targets():
    out = [row("forum", f"F{i}") for i in range(3)]
    out += [row("creator", f"C{i}") for i in range(6)]
    out += [row("x_account", f"X{i}") for i in range(6)]
    # discord: D0 outside the size window, D1 matches, D2 in window but no sport, D3 matches
    out += [row("discord_server", "D0", size="100 members", focus="MLB"),
            row("discord_server", "D1", size="2.4K members", focus="NFL props"),
            row("discord_server", "D2", size="1K members", focus="chat"),
            row("discord_server", "D3", size="813 members", focus="MLB")]
    out += [row("discord_server", f"D{i}", size="9K members", focus="x") for i in range(4, 16)]
    return out


class Selection(unittest.TestCase):
    def test_quotas_and_order(self):
        picked = ob.select_targets(many_targets(), set())
        self.assertEqual(len(picked), 20)
        kinds = [r["type"] for r in picked]
        self.assertEqual(kinds, ["forum"] * 2 + ["creator"] * 5 + ["x_account"] * 5 + ["discord_server"] * 8)
        self.assertEqual(names(picked)[:2], ["F0", "F1"])
        self.assertEqual(names(picked)[2:7], [f"C{i}" for i in range(5)])

    def test_discord_prefers_mid_size_mlb_nfl_props_then_fills_in_file_order(self):
        discord = [r for r in ob.select_targets(many_targets(), set()) if r["type"] == "discord_server"]
        self.assertEqual(names(discord)[:2], ["D1", "D3"])
        # then the rest in the order the rows appear: D0, D2, D4...
        self.assertEqual(names(discord)[2:5], ["D0", "D2", "D4"])

    def test_skips_already_contacted_not_allowed_unverified_and_competitor(self):
        t = many_targets()
        t[0]["rule_status"] = "NOT_ALLOWED (promotion)"
        t[1]["rule_status"] = "UNVERIFIED: ask modmail first"
        t[3]["rule_status"] = "ALLOWED_WITH_CONDITIONS (possible Competitor)"
        picked = names(ob.select_targets(t, {ob.norm_name("c1")}))
        for gone in ("F0", "F1", "C0", "C1"):
            self.assertNotIn(gone, picked)
        self.assertIn("F2", picked)

    def test_short_type_gives_remainder_to_discord(self):
        t = [r for r in many_targets() if r["type"] != "x_account"]
        picked = ob.select_targets(t, set())
        self.assertEqual(len(picked), 20)
        self.assertEqual(sum(r["type"] == "discord_server" for r in picked), 13)

    def test_no_repeat_within_or_across_batches(self):
        t = many_targets()
        first = ob.select_targets(t, set())
        second = ob.select_targets(t, set(), exclude={ob.norm_name(n) for n in names(first)})
        self.assertFalse(set(names(first)) & set(names(second)))
        dup = ob.select_targets(t + [row("forum", "f0")], set())
        self.assertEqual(len([n for n in names(dup) if n.lower() == "f0"]), 1)

    def test_member_parsing(self):
        self.assertEqual(ob.parse_members("2.4K members / 120 online"), 2400)
        self.assertEqual(ob.parse_members("10,025 members / 336 online"), 10025)
        self.assertEqual(ob.parse_members("813 members"), 813)
        self.assertIsNone(ob.parse_members("subscribers not shown"))


class ParsedText(unittest.TestCase):
    def test_text_comes_from_the_scripts_file(self):
        s = ob.parse_scripts(SCRIPTS)
        self.assertEqual(s["variant_b"], "Hi [Name], B text. I'm not claiming an edge. Look at the record page?")
        self.assertEqual(s["post_title"], "The title. The MLB number is negative.")
        self.assertIn("1. First question.", s["post_body"])
        self.assertIn("\n\n", s["post_body"])  # blank '>' lines survive
        self.assertTrue(s["x_reply"].startswith("[One specific thing"))

    def test_missing_section_raises_naming_it(self):
        broken = SCRIPTS.replace("**Variant B, feedback first (10 words)**", "**Something else**")
        with self.assertRaises(ob.OutreachError) as cm:
            ob.parse_scripts(broken)
        self.assertIn("Variant B", str(cm.exception))
        with self.assertRaises(ob.OutreachError) as cm:
            ob.parse_scripts(SCRIPTS.replace("## (c) Reply template for X", "## (c) Other"))
        self.assertIn("Reply template for X", str(cm.exception))

    def test_main_exits_2_when_a_section_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), scripts=SCRIPTS.replace("**Title:**", "**Heading:**"))
            err = io.StringIO()
            with redirect_stderr(err):
                code = ob.main(["build", "--batch", "1"], root=root, record_fn=lambda: RECORD)
            self.assertEqual(code, 2)
            self.assertIn("Title", err.getvalue())
            self.assertFalse((root / "docs" / "sales" / "batch_01.md").exists())


class Fills(unittest.TestCase):
    def test_record_phrase_formats_from_the_record(self):
        self.assertEqual(ob.record_phrase(RECORD), "16-17, -5.05 units over 6 graded nights")
        self.assertEqual(ob.record_phrase(dict(RECORD, days=1, wins=0, losses=1, profit_units=-1.0)),
                         "0-1, -1.00 units over 1 graded night")

    def test_non_negative_record_is_refused(self):
        with self.assertRaises(ob.OutreachError):
            ob.record_phrase(dict(RECORD, profit_units=0.4))
        with self.assertRaises(ob.OutreachError):
            ob.record_phrase({})

    def test_fills_and_placeholders_left_visible(self):
        s = ob.parse_scripts(SCRIPTS)
        creator = ob.build_item(row("creator", "C"), s, "16-17, -5.05 units over 6 graded nights", URL)
        self.assertIn("[Name]", creator["messages"][0]["text"])
        self.assertEqual(creator["notes"], [ob.NOTE_NAME])
        x = ob.build_item(row("x_account", "X"), s, "16-17, -5.05 units over 6 graded nights", URL)
        text = x["messages"][0]["text"]
        self.assertIn("16-17, -5.05 units over 6 graded nights", text)
        self.assertNotIn("[MLB_RECORD]", text)
        self.assertIn("[One specific thing", text)
        self.assertEqual(x["notes"], [ob.NOTE_X])

    def test_forum_gets_record_link_and_filled_record(self):
        s = ob.parse_scripts(SCRIPTS)
        forum = ob.build_item(row("forum", "F"), s, "16-17, -5.05 units over 6 graded nights", URL)
        body = forum["messages"][1]["text"]
        self.assertIn("16-17, -5.05 units over 6 graded nights", body)
        self.assertTrue(body.endswith(f"Record page: {URL}"))
        self.assertEqual(forum["messages"][0]["text"], s["post_title"])

    def test_no_link_in_cold_discord_or_x_first_message(self):
        s = ob.parse_scripts(SCRIPTS)
        for kind in ("discord_server", "x_account", "creator"):
            item = ob.build_item(row(kind, "T"), s, "16-17, -5.05 units over 6 graded nights", URL)
            for msg in item["messages"]:
                self.assertNotIn("http", msg["text"])
                self.assertNotIn("RECORD_URL", msg["text"])
            self.assertEqual(ob.guard_item(item, ob.allowed_edge_forms(SCRIPTS)), [])
        # CHANGED by review: one first message, not a bare statement followed
        # by a held-back second. It opens with the greeting and the line
        # written for this target, and ends with Variant B's own disclosure
        # and question, so there is something to answer.
        discord = ob.build_item(row("discord_server", "T", first="Your room is great."), s, "x", URL)
        self.assertEqual(len(discord["messages"]), 1)
        text = discord["messages"][0]["text"]
        self.assertTrue(text.startswith("Hi [Name], your room is great."), text)
        self.assertIn("not claiming an edge", text)
        self.assertTrue(text.endswith("?"), text)

    def test_a_proper_name_keeps_its_capital_after_the_greeting(self):
        s = ob.parse_scripts(SCRIPTS)
        item = ob.build_item(row("creator", "T", first="Unit Circle's pitch is plain."), s, "x", URL)
        self.assertTrue(item["messages"][0]["text"].startswith("Hi [Name], Unit Circle's pitch is plain."))

    def test_a_link_in_a_cold_message_is_caught(self):
        item = {"messages": [{"label": "m", "cold": True, "text": "see https://x.test"}]}
        self.assertTrue(ob.guard_item(item, ()))
        item = {"messages": [{"label": "m", "cold": True, "text": "see [RECORD_URL]"}]}
        self.assertTrue(ob.guard_item(item, ()))


class Guard(unittest.TestCase):
    ALLOWED = ob.allowed_edge_forms(SCRIPTS)

    def test_allowed_forms_come_from_the_source(self):
        self.assertIn("no edge claimed", self.ALLOWED)
        self.assertIn("i am not claiming an edge", self.ALLOWED)
        self.assertNotIn("no edge is claimed", self.ALLOWED)  # not in the fixture, so not allowed

    def test_banned_words_and_stray_edge_are_flagged(self):
        for bad in ("a profit today", "a lock of the day", "sharp bettors", "winning streak",
                    "guaranteed", "uses Bet Check", "we have an edge"):
            self.assertTrue(ob.guard_message(bad, self.ALLOWED), bad)

    def test_allowed_edge_phrases_pass(self):
        for good in ("No edge claimed.", "I'm not claiming an edge.", "I’m not claiming an edge.",
                     "I am not claiming an edge and no edge claimed."):
            self.assertEqual(ob.guard_message(good, self.ALLOWED), [], good)
        self.assertTrue(ob.guard_message("no edge is claimed", self.ALLOWED))  # form not in source

    def test_edit_and_knowledge_are_not_edge(self):
        self.assertEqual(ob.guard_message("nothing can be edited; knowledge", self.ALLOWED), [])

    def test_build_aborts_exit_2_on_a_guard_hit_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets = [row("discord_server", "D", first="We post a lock every night.")]
            root = _tree(Path(tmp), targets=targets)
            err = io.StringIO()
            with redirect_stderr(err):
                code = ob.main(["build", "--batch", "1"], root=root, record_fn=lambda: RECORD)
            self.assertEqual(code, 2)
            self.assertIn("lock", err.getvalue())
            self.assertIn("D", err.getvalue())
            self.assertFalse((root / "docs" / "sales" / "batch_01.md").exists())


class BuildEndToEnd(unittest.TestCase):
    def test_build_writes_items_and_sent_logs_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), targets=many_targets())
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(ob.main(["build", "--batch", "1", "--date", "2026-10-01"],
                                         root=root, record_fn=lambda: RECORD), 0)
                text = (root / "docs" / "sales" / "batch_01.md").read_text(encoding="utf-8")
                items = ob.parse_batch(text)
                self.assertEqual(len(items), 20)
                self.assertIn("16-17, -5.05 units over 6 graded nights", text)
                self.assertIn("day 3 2026-10-04, day 7 2026-10-08", text)
                self.assertIn("python scripts/outreach_batch.py sent --batch 1", text)
                code = ob.main(["sent", "--batch", "1", "--items", "1,3", "--date", "2026-10-02"], root=root)
            self.assertEqual(code, 0)
            _, rows = ob.read_pipeline(root / "docs" / "sales" / "pipeline.csv")
            self.assertEqual([r["target"] for r in rows], [items[0]["name"], items[2]["name"]])
            self.assertEqual(rows[0]["next_action"], "follow up 2026-10-05")
            # a rebuild of a partly sent batch is refused, and a second batch skips both batches
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                self.assertEqual(ob.main(["build", "--batch", "1"], root=root, record_fn=lambda: RECORD), 2)
                self.assertEqual(ob.main(["build", "--batch", "2", "--size", "6"],
                                         root=root, record_fn=lambda: RECORD), 0)
            second = ob.parse_batch((root / "docs" / "sales" / "batch_02.md").read_text(encoding="utf-8"))
            self.assertFalse({i["name"] for i in items} & {i["name"] for i in second})


def _tree(base: Path, scripts=SCRIPTS, targets=None):
    sales = base / "docs" / "sales"
    sales.mkdir(parents=True)
    (base / "config").mkdir()
    (base / "config" / "business.json").write_text(
        '{"public_urls": {"record": "%s"}}' % URL, encoding="utf-8")
    (sales / "scripts.md").write_text(scripts, encoding="utf-8")
    (sales / "channels.md").write_text(CHANNELS, encoding="utf-8")
    fields = ["type", "name", "url", "size", "sport_focus", "why_fit", "contact_path", "rule_status",
              "first_line", "checked"]
    with (sales / "targets.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(targets or [])
    (sales / "pipeline.csv").write_text(",".join(ob.PIPELINE_FIELDS) + "\n", encoding="utf-8")
    return base


class PipelineLog(unittest.TestCase):
    ITEMS = [{"n": 1, "type": "discord_server", "name": "Alpha, Inc", "url": "https://a.test",
              "contact_path": "c", "variant": "first_line + Variant B"},
             {"n": 2, "type": "creator", "name": "Beta", "url": "https://b.test", "contact_path": "c",
              "variant": "Variant B"}]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "pipeline.csv"
        self.path.write_bytes((",".join(ob.PIPELINE_FIELDS) + "\r\nold,old,old,Old Row,,,sent,,,0,\r\n").encode())

    def test_sent_appends_rows_and_leaves_earlier_bytes_untouched(self):
        before = self.path.read_bytes()
        fields, history = ob.read_pipeline(self.path)
        rows = ob.sent_rows(self.ITEMS, 1, date(2026, 10, 1), "from batch")
        ob.append_rows(self.path, fields, rows)
        after = self.path.read_bytes()
        self.assertTrue(after.startswith(before))
        added = after[len(before):].decode()
        self.assertNotIn("\r", added)
        parsed = list(csv.DictReader(io.StringIO(added, newline=""), fieldnames=fields))
        self.assertEqual([r["target"] for r in parsed], ["Alpha, Inc", "Beta"])  # comma survives quoting
        self.assertEqual(parsed[0]["stage"], "sent")
        self.assertEqual(parsed[0]["source"], "discord_server")
        self.assertEqual(parsed[0]["campaign"], "batch_01")
        self.assertEqual(parsed[0]["next_action"], "follow up 2026-10-04")
        self.assertEqual(parsed[0]["revenue"], "0")
        self.assertEqual(parsed[0]["notes"], "https://a.test | from batch")

    def test_sent_refuses_a_target_already_in_the_file(self):
        _, history = ob.read_pipeline(self.path)
        with self.assertRaises(ob.OutreachError):
            ob.check_new_targets(["  old row "], ob.pipeline_names(history))
        with self.assertRaises(ob.OutreachError):
            ob.check_new_targets(["X", "x"], set())

    def test_main_sent_refuses_duplicate_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), targets=many_targets())
            with redirect_stdout(io.StringIO()):
                ob.main(["build", "--batch", "1"], root=root, record_fn=lambda: RECORD)
                self.assertEqual(ob.main(["sent", "--batch", "1", "--items", "1"], root=root), 0)
            pipe = root / "docs" / "sales" / "pipeline.csv"
            before = pipe.read_bytes()
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                self.assertEqual(ob.main(["sent", "--batch", "1", "--items", "1,2"], root=root), 2)
                self.assertEqual(ob.main(["sent", "--batch", "1", "--items", "99"], root=root), 2)
            self.assertEqual(pipe.read_bytes(), before)

    def test_append_adds_a_missing_final_newline_without_touching_earlier_bytes(self):
        self.path.write_bytes(b"date,target\n2026,Old")
        ob.append_rows(self.path, ["date", "target"], [{"date": "d", "target": "T"}])
        self.assertEqual(self.path.read_bytes(), b"date,target\n2026,Old\nd,T\n")

    def test_reply_appends_a_new_row_and_keeps_history(self):
        fields, history = ob.read_pipeline(self.path)
        ob.append_rows(self.path, fields, ob.sent_rows(self.ITEMS, 1, date(2026, 10, 1)))
        before = self.path.read_bytes()
        fields, history = ob.read_pipeline(self.path)
        new = ob.reply_row(history, "alpha, inc", "replied", date(2026, 10, 3), "0", "asked for link")
        ob.append_rows(self.path, fields, [new])
        self.assertTrue(self.path.read_bytes().startswith(before))
        _, rows = ob.read_pipeline(self.path)
        mine = [r for r in rows if r["target"] == "Alpha, Inc"]
        self.assertEqual([r["stage"] for r in mine], ["sent", "replied"])
        self.assertEqual(mine[1]["campaign"], "batch_01")
        self.assertEqual(mine[1]["notes"], "asked for link")

    def test_reply_refuses_unknown_target_bad_stage_and_same_stage(self):
        fields, history = ob.read_pipeline(self.path)
        with self.assertRaises(ob.OutreachError):
            ob.reply_row(history, "Nobody", "replied", date(2026, 10, 3))
        with self.assertRaises(ob.OutreachError):
            ob.reply_row(history, "Old Row", "sent", date(2026, 10, 3))
        with self.assertRaises(ob.OutreachError):
            ob.reply_row(history, "Old Row", "paid", date(2026, 10, 3), revenue="lots")
        again = history + [dict(history[0], stage="replied")]
        with self.assertRaises(ob.OutreachError):
            ob.reply_row(again, "Old Row", "replied", date(2026, 10, 3))



class OnePersonOncePerBatch(unittest.TestCase):
    """Added by review: the first real batch wrote to Peter Appel twice (as a
    site's editor and as an X account) and included a seller of picks whose
    'possible competitor' note sat in why_fit rather than rule_status."""

    def _row(self, kind, name, why="fits", status="ALLOWED_WITH_CONDITIONS"):
        return {"type": kind, "name": name, "url": "https://example.test/" + name[:6],
                "size": "1,000 members", "sport_focus": "MLB", "why_fit": why,
                "contact_path": "DM", "rule_status": status, "first_line": "Hello.",
                "checked": "2026-10-01"}

    def test_the_same_person_is_not_picked_under_two_names(self):
        targets = [self._row("creator", "JustBaseball Betting (Peter Appel, TheDannyClassic)"),
                   self._row("x_account", "Peter Appel (@PeterAppel23)"),
                   self._row("x_account", "Joseph Buchdahl (@12Xpert)")]
        names = [r["name"] for r in ob.select_targets(targets, set(), size=20)]
        self.assertIn("JustBaseball Betting (Peter Appel, TheDannyClassic)", names)
        self.assertNotIn("Peter Appel (@PeterAppel23)", names)
        self.assertIn("Joseph Buchdahl (@12Xpert)", names)

    def test_a_person_in_an_earlier_batch_is_not_picked_again_under_another_name(self):
        # Batch 2 first came out with Peter Appel and Farley in it again.
        earlier = (ob.people({"name": "JustBaseball Betting (Peter Appel, TheDannyClassic)"})
                   | ob.people({"name": "Farley's Substack"}))
        targets = [self._row("x_account", "Peter Appel (@PeterAppel23)"),
                   self._row("x_account", "Farley (@FarleyBets)"),
                   self._row("x_account", "Joseph Buchdahl (@12Xpert)")]
        names = [r["name"] for r in ob.select_targets(targets, set(), size=20, exclude_people=earlier)]
        self.assertEqual(names, ["Joseph Buchdahl (@12Xpert)"])
        # and without the earlier batch they are all eligible
        self.assertEqual(len(ob.select_targets(targets, set(), size=20)), 3)

    def test_people_reads_the_name_and_the_brackets_and_drops_handles(self):
        self.assertIn("peter appel", ob.people({"name": "Peter Appel (@PeterAppel23)"}))
        self.assertNotIn("@peterappel23", ob.people({"name": "Peter Appel (@PeterAppel23)"}))
        self.assertTrue({"justbaseball betting", "peter appel", "thedannyclassic"}
                        <= ob.people({"name": "JustBaseball Betting (Peter Appel, TheDannyClassic)"}))

    def test_a_possessive_first_name_is_the_same_person(self):
        self.assertTrue(ob.people({"name": "Farley's Substack"}) & ob.people({"name": "Farley (@FarleyBets)"}))
        # generic first words do not link unrelated targets
        self.assertFalse(ob.people({"name": "Fantasy Football Addicts"})
                         & ob.people({"name": "Fantasy Baseball Discord"}))

    def test_a_competitor_named_only_in_the_fit_note_is_skipped(self):
        seller = self._row("creator", "Paid Picks Letter", why="possible competitor: sells a paid group")
        self.assertFalse(ob.eligible(seller))
        self.assertTrue(ob.eligible(self._row("creator", "A Critic")))


if __name__ == "__main__":
    unittest.main()
