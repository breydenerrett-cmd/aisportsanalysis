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


def _tree(base: Path, scripts=SCRIPTS, targets=None, url=URL):
    sales = base / "docs" / "sales"
    sales.mkdir(parents=True)
    (base / "config").mkdir()
    (base / "config" / "business.json").write_text(
        '{"public_urls": {"record": "%s"}}' % url, encoding="utf-8")
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


HASH_URL = "https://example.test/web/index.html#/record-card"


def big_targets():
    """Enough distinct targets for two full batches of 20 (names short, so no first-word collisions)."""
    out = [row("forum", f"F{i}") for i in range(6)]
    out += [row("creator", f"C{i}") for i in range(12)]
    out += [row("x_account", f"X{i}") for i in range(12)]
    out += [row("discord_server", f"D{i}", size="1K members", focus="MLB") for i in range(24)]
    return out


def run(root, *argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ob.main(list(argv), root=root, record_fn=lambda: RECORD)
    return code, out.getvalue(), err.getvalue()


def queue_of(root):
    return ob.read_queue(root / "docs" / "sales" / ob.QUEUE_NAME)


def snapshot(root):
    sales = root / "docs" / "sales"
    return {p.name: p.read_bytes() for p in sorted(sales.glob("*")) if p.is_file()}


class QueueSeed(unittest.TestCase):
    """One row per LEAD, seeded from the batch files, never the same person twice."""

    def _two_batches(self, tmp):
        root = _tree(Path(tmp), targets=big_targets())
        self.assertEqual(run(root, "build", "--batch", "1", "--date", "2026-10-01")[0], 0)
        self.assertEqual(run(root, "build", "--batch", "2", "--date", "2026-10-01")[0], 0)
        return root

    def test_two_batches_give_forty_distinct_leads_and_no_person_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = queue_of(self._two_batches(tmp))
            self.assertEqual(len(rows), 40)
            ids = [r["lead_id"] for r in rows]
            self.assertEqual(len(set(ids)), 40)
            for lid in ids:
                self.assertRegex(lid, r"^[a-z0-9-]{1,40}$")
            seen = set()
            for r in rows:
                keys = ob.people({"name": r["person_channel"]})
                self.assertFalse(seen & keys, r["person_channel"])
                seen |= keys
            self.assertEqual({r["batch"] for r in rows}, {"1", "2"})
            self.assertEqual(list(rows[0].keys()), ob.QUEUE_FIELDS)
            self.assertTrue(all(not r["sent_at"] and not r["payment_at"] for r in rows))

    def test_seed_from_legacy_batch_files_numbers_leads_in_file_order_and_is_idempotent(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_batches(tmp)
            sales = root / "docs" / "sales"
            first = [r["person_channel"] for r in queue_of(root)]
            for name in ("batch_01.md", "batch_02.md"):      # make them look like pre-queue files
                text = (sales / name).read_text(encoding="utf-8")
                (sales / name).write_text(re.sub(r', "lead_id": "[^"]*"', "", text), encoding="utf-8")
            (sales / ob.QUEUE_NAME).unlink()
            code, out, _ = run(root, "seed")
            self.assertEqual(code, 0, out)
            rows = queue_of(root)
            self.assertEqual([r["person_channel"] for r in rows], first)
            self.assertEqual(rows[0]["lead_id"][:5], "l001-")
            self.assertEqual(rows[39]["lead_id"][:5], "l040-")
            before = snapshot(root)
            self.assertEqual(run(root, "seed")[0], 0)
            self.assertEqual(snapshot(root), before)

    def test_a_second_channel_for_the_same_person_is_refused(self):
        base = ob.add_leads([], [{"name": "JustBaseball Betting (Peter Appel, TheDannyClassic)",
                                  "type": "creator", "sport": "MLB", "batch": 1},
                                 {"name": "Farley's Substack", "type": "creator", "batch": 1}])
        for alias in ("Peter Appel (@PeterAppel23)",                     # a name inside the brackets
                      "Farley (@FarleyBets)",                            # a possessive first name
                      "  justbaseball betting (peter appel, thedannyclassic) "):   # same name, other spacing
            with self.assertRaises(ob.OutreachError, msg=alias) as cm:
                ob.add_leads(base, [{"name": alias, "type": "x_account", "batch": 2}])
            self.assertIn("one person is one lead", str(cm.exception))
        self.assertEqual(len(ob.add_leads(base, [{"name": "Joseph Buchdahl (@12Xpert)",
                                                  "type": "x_account", "batch": 2}])), 3)
        with self.assertRaises(ob.OutreachError):       # twice in the same call
            ob.add_leads([], [{"name": "Z", "type": "creator"}, {"name": "z", "type": "creator"}])

    def test_seed_refuses_a_batch_file_that_lists_one_person_twice_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), targets=[row("creator", "JustBaseball Betting (Peter Appel, X)"),
                                             row("x_account", "Peter Appel (@PeterAppel23)")])
            sales = root / "docs" / "sales"
            meta = ('<!--ITEM {"n": 1, "type": "%s", "name": "%s", "url": "", "contact_path": "", '
                    '"variant": "v"}-->\n')
            (sales / "batch_01.md").write_text(
                meta % ("creator", "JustBaseball Betting (Peter Appel, X)")
                + meta % ("x_account", "Peter Appel (@PeterAppel23)"), encoding="utf-8")
            before = snapshot(root)
            code, _, err = run(root, "seed")
            self.assertEqual(code, 2)
            self.assertIn("same person", err)
            self.assertEqual(snapshot(root), before)
            self.assertFalse((sales / ob.QUEUE_NAME).exists())

    def test_lead_ids_are_url_safe_and_at_most_forty_characters(self):
        long = "Ünïcode & Punctuation's Extremely Long Community Name For Sports Betting (Owner)"
        lid = ob.make_lead_id(7, long)
        self.assertLessEqual(len(lid), 40)
        self.assertRegex(lid, r"^l007-[a-z0-9-]+$")
        self.assertFalse(lid.endswith("-"))
        self.assertEqual(ob.make_lead_id(12, "Unit Circle"), "l012-unit-circle")
        self.assertEqual(ob.make_lead_id(5, "Farley's Substack"), "l005-farleys-substack")
        self.assertRegex(ob.make_lead_id(1, "!!!"), r"^l001-lead$")

    def test_the_committed_queue_matches_the_committed_batch_files(self):
        """Reads the real repo on purpose: it guards the artifact Brey works from."""
        root = Path(__file__).resolve().parents[1]
        rows = ob.read_queue(root / "docs" / "sales" / ob.QUEUE_NAME)
        ids = [r["lead_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        seen = set()
        for r in rows:
            keys = ob.people({"name": r["person_channel"]})
            self.assertFalse(seen & keys, r["person_channel"])
            seen |= keys
        by_id = {r["lead_id"]: r for r in rows}
        for path in sorted((root / "docs" / "sales").glob("batch_*.md")):
            for item in ob.parse_batch(path.read_text(encoding="utf-8")):
                self.assertIn(item["lead_id"], by_id, item["name"])
                self.assertEqual(by_id[item["lead_id"]]["person_channel"], item["name"])


class QueueCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = _tree(Path(self.tmp.name), targets=big_targets())
        run(self.root, "build", "--batch", "1", "--date", "2026-10-01")
        self.assertEqual(run(self.root, "sent", "--batch", "1", "--items", "1,2",
                             "--at", "2026-10-02T09:00:00Z")[0], 0)
        self.a, self.b, self.unsent = [r["lead_id"] for r in queue_of(self.root)[:3]]

    def lead(self, lead_id):
        return next(r for r in queue_of(self.root) if r["lead_id"] == lead_id)

    def test_sent_stamps_the_row_and_sets_the_day_three_followup(self):
        row = self.lead(self.a)
        self.assertEqual(row["sent_at"], "2026-10-02T09:00:00Z")
        self.assertEqual(row["next_followup"], "2026-10-05")
        self.assertEqual(row["message_version"], "feedback post + record link")
        self.assertEqual(self.lead(self.unsent)["sent_at"], "")

    def test_reply_signup_activated_would_pay_paid_update_one_row_and_never_add_a_lead(self):
        pipe = self.root / "docs" / "sales" / "pipeline.csv"
        before_events = len(ob.read_pipeline(pipe)[1])
        steps = [("reply", "--classification", "interested"), ("signup",), ("activated",),
                 ("would-pay",), ("paid", "--revenue", "19.99")]
        for n, step in enumerate(steps):
            code, out, err = run(self.root, *step[:1], "--lead", self.a, *step[1:],
                                 "--at", f"2026-10-0{3 + n}T10:00:00Z")
            self.assertEqual(code, 0, err)
            rows = queue_of(self.root)
            self.assertEqual(len(rows), 20)                              # still 20 rows
            self.assertEqual(ob.queue_counts(rows)["leads"], 20)         # still 20 leads
        row = self.lead(self.a)
        self.assertEqual((row["reply_at"], row["reply_classification"]), ("2026-10-03T10:00:00Z", "interested"))
        self.assertEqual(row["signup_at"], "2026-10-04T10:00:00Z")
        self.assertEqual(row["activated_at"], "2026-10-05T10:00:00Z")
        self.assertEqual(row["would_pay_at"], "2026-10-06T10:00:00Z")
        self.assertEqual(row["payment_at"], "2026-10-07T10:00:00Z")
        counts = ob.queue_counts(queue_of(self.root))
        self.assertEqual((counts["sent"], counts["replies"], counts["signups"], counts["activated"],
                          counts["would_pay"], counts["paid"]), (2, 1, 1, 1, 1, 1))
        events = ob.read_pipeline(pipe)[1][before_events:]
        self.assertEqual([e["stage"] for e in events], ["replied", "signup", "active", "would_pay", "paid"])
        self.assertTrue(all(f"lead_id={self.a}" in e["notes"] for e in events))
        self.assertEqual(events[-1]["revenue"], "19.99")
        total, unknown = ob.queue_revenue(queue_of(self.root), ob.read_pipeline(pipe)[1])
        self.assertEqual((round(total, 2), unknown), (19.99, 0))

    def test_a_timestamp_is_set_once_and_never_overwritten(self):
        self.assertEqual(run(self.root, "signup", "--lead", self.a, "--at", "2026-10-03T10:00:00Z")[0], 0)
        before = snapshot(self.root)
        code, _, err = run(self.root, "signup", "--lead", self.a, "--at", "2026-10-09T10:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("already recorded", err)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(self.lead(self.a)["signup_at"], "2026-10-03T10:00:00Z")

    def test_an_auto_reply_is_not_a_reply_and_the_first_real_one_replaces_it(self):
        run(self.root, "reply", "--lead", self.a, "--classification", "auto", "--at", "2026-10-03T08:00:00Z")
        counts = ob.queue_counts(queue_of(self.root))
        self.assertEqual((counts["replied_any"], counts["replies"], counts["auto_replies"]), (1, 0, 1))
        self.assertIsNone(ob.milestones(queue_of(self.root))["first_reply"])
        self.assertEqual(run(self.root, "reply", "--lead", self.a, "--classification", "auto")[0], 2)
        run(self.root, "reply", "--lead", self.a, "--classification", "question", "--at", "2026-10-04T08:00:00Z")
        row = self.lead(self.a)
        self.assertEqual((row["reply_at"], row["reply_classification"]), ("2026-10-04T08:00:00Z", "question"))
        # a later reclassification keeps the first real reply's time
        run(self.root, "reply", "--lead", self.a, "--classification", "interested", "--at", "2026-10-06T08:00:00Z")
        row = self.lead(self.a)
        self.assertEqual((row["reply_at"], row["reply_classification"]), ("2026-10-04T08:00:00Z", "interested"))
        self.assertIn("question -> interested", row["notes"])
        # an auto-reply after a real one tells us nothing
        self.assertEqual(run(self.root, "reply", "--lead", self.a, "--classification", "auto")[0], 2)

    def test_illegal_transitions_exit_2_and_leave_every_file_byte_identical(self):
        run(self.root, "signup", "--lead", self.a, "--at", "2026-10-03T10:00:00Z")
        cases = [
            ("reply", "--lead", self.unsent, "--classification", "interested"),   # reply before sent
            ("signup", "--lead", self.unsent),
            ("paid", "--lead", self.unsent),
            ("would-pay", "--lead", self.unsent),
            ("followup", "--lead", self.unsent, "--date", "2026-10-09"),
            ("activated", "--lead", self.b),                                      # activated before signup
            ("reply", "--lead", "l999-nobody", "--classification", "interested"),  # unknown lead
            ("signup", "--lead", "l999-nobody"),
            ("reply", "--lead", self.a, "--classification", "ecstatic"),          # unknown classification
            ("reply", "--lead", self.a),                                          # neither form
            ("signup", "--lead", self.b, "--at", "2026-10-01T00:00:00Z"),         # before it was sent
            ("signup", "--lead", self.b, "--at", "not-a-time"),
            ("paid", "--lead", self.a, "--revenue", "-5"),
            ("followup", "--lead", self.a, "--date", "next week"),
            ("sent", "--batch", "1", "--items", "1"),                             # already sent
            ("sent", "--batch", "1", "--items", "3,99"),                          # one bad item voids the call
            ("signup", "--lead", self.a),                                         # already signed up
        ]
        for argv in cases:
            before = snapshot(self.root)
            code, _, err = run(self.root, *argv)
            self.assertEqual(code, 2, (argv, err))
            self.assertIn("refused:", err)
            self.assertEqual(snapshot(self.root), before, argv)

    def test_followup_sets_the_next_date_and_can_be_moved(self):
        self.assertEqual(run(self.root, "followup", "--lead", self.a, "--date", "2026-10-09")[0], 0)
        self.assertEqual(self.lead(self.a)["next_followup"], "2026-10-09")
        self.assertEqual(run(self.root, "followup", "--lead", self.a, "--date", "2026-10-12")[0], 0)
        self.assertEqual(self.lead(self.a)["next_followup"], "2026-10-12")
        self.assertEqual(len(queue_of(self.root)), 20)

    def test_a_lead_can_be_named_by_its_person_channel(self):
        name = self.lead(self.a)["person_channel"]
        self.assertEqual(run(self.root, "signup", "--target", name.lower(), "--at", "2026-10-03T10:00:00Z")[0], 0)
        self.assertTrue(self.lead(self.a)["signup_at"])

    def test_milestones_print_the_first_timestamp_of_each_step_or_not_yet(self):
        code, out, _ = run(self.root, "milestones")
        self.assertEqual(code, 0)
        self.assertIn("First message sent: 2026-10-02T09:00:00Z", out)
        self.assertIn("First signup: not yet", out)
        self.assertIn("First payment: not yet", out)
        run(self.root, "reply", "--lead", self.b, "--classification", "auto", "--at", "2026-10-02T09:30:00Z")
        run(self.root, "reply", "--lead", self.a, "--classification", "question", "--at", "2026-10-03T12:00:00Z")
        run(self.root, "reply", "--lead", self.b, "--classification", "interested", "--at", "2026-10-03T08:00:00Z")
        run(self.root, "signup", "--lead", self.a, "--at", "2026-10-05T12:00:00Z")
        run(self.root, "signup", "--lead", self.b, "--at", "2026-10-04T12:00:00Z")
        found = ob.milestones(queue_of(self.root))
        self.assertEqual(found["first_sent"], "2026-10-02T09:00:00Z")
        self.assertEqual(found["first_reply"], "2026-10-03T08:00:00Z")     # the auto at 09:30 never counted
        self.assertEqual(found["first_interested"], "2026-10-03T08:00:00Z")
        self.assertEqual(found["first_signup"], "2026-10-04T12:00:00Z")
        self.assertIsNone(found["first_active"])
        self.assertIsNone(found["first_payment"])
        self.assertIn("First signup: 2026-10-04T12:00:00Z", run(self.root, "milestones")[1])

    def test_the_legacy_stage_form_still_works_and_says_it_left_the_queue_alone(self):
        name = self.lead(self.a)["person_channel"]
        before = (self.root / "docs" / "sales" / ob.QUEUE_NAME).read_bytes()
        code, out, _ = run(self.root, "reply", "--target", name, "--stage", "replied", "--date", "2026-10-03")
        self.assertEqual(code, 0)
        self.assertIn("queue", out)
        self.assertEqual((self.root / "docs" / "sales" / ob.QUEUE_NAME).read_bytes(), before)


class TaggedLinks(unittest.TestCase):
    def test_tag_url_puts_the_query_before_the_fragment(self):
        self.assertEqual(
            ob.tag_url("https://host/web/index.html#/record-card", "l012-unit-circle", "discord_server", 1),
            "https://host/web/index.html?utm_source=l012-unit-circle&utm_medium=discord_server"
            "&utm_campaign=batch_01#/record-card")
        self.assertEqual(ob.tag_url("https://host/r", "l001-a", "forum", 12),
                         "https://host/r?utm_source=l001-a&utm_medium=forum&utm_campaign=batch_12")
        self.assertEqual(ob.tag_url("https://host/r?x=1#/h", "l001-a", "forum", 2),
                         "https://host/r?x=1&utm_source=l001-a&utm_medium=forum&utm_campaign=batch_02#/h")

    def test_tag_url_refuses_a_bad_lead_id_a_bad_medium_and_existing_utm(self):
        for bad in ("L001-A", "l001 a", "l001-" + "a" * 40, ""):
            with self.assertRaises(ob.OutreachError, msg=bad):
                ob.tag_url("https://host/r", bad, "forum", 1)
        with self.assertRaises(ob.OutreachError):
            ob.tag_url("https://host/r", "l001-a", "Forum Thread", 1)
        with self.assertRaises(ob.OutreachError):
            ob.tag_url("https://host/r?utm_source=x", "l001-a", "forum", 1)

    def test_every_record_link_in_a_built_batch_carries_its_lead_and_the_base_comes_from_config(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), targets=big_targets(), url=HASH_URL)
            self.assertEqual(run(root, "build", "--batch", "1", "--date", "2026-10-01")[0], 0)
            text = (root / "docs" / "sales" / "batch_01.md").read_text(encoding="utf-8")
            ids = {r["lead_id"] for r in queue_of(root)}
            links = re.findall(r"https://example\.test/web/index\.html\S*", text)
            self.assertGreaterEqual(len(links), 20)          # 2 forum bodies + 18 "if they ask" lines
            for link in links:
                m = re.fullmatch(r"https://example\.test/web/index\.html\?utm_source=([a-z0-9-]+)"
                                 r"&utm_medium=(forum|creator|x_account|discord_server)"
                                 r"&utm_campaign=batch_01#/record-card", link)
                self.assertIsNotNone(m, link)
                self.assertIn(m.group(1), ids)
            forum = next(i for i in ob.parse_batch(text) if i["type"] == "forum")
            self.assertIn(f"Record page: https://example.test/web/index.html?utm_source={forum['lead_id']}"
                          f"&utm_medium=forum&utm_campaign=batch_01#/record-card", text)
            # the cold messages still carry no link
            for block in re.findall(r"```\n(.*?)\n```", text, re.S):
                if "I'm the builder" not in block and "```" not in block and "sent --batch" not in block \
                        and "reply --lead" not in block:
                    self.assertNotIn("http", block)

    def test_switching_the_domain_is_one_config_edit_plus_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), targets=big_targets(), url=HASH_URL)
            run(root, "build", "--batch", "1", "--date", "2026-10-01")
            (root / "config" / "business.json").write_text(
                '{"public_urls": {"record": "https://linehound.app/web/index.html#/record-card"}}',
                encoding="utf-8")
            self.assertEqual(run(root, "rebuild", "--batch", "1")[0], 0)
            text = (root / "docs" / "sales" / "batch_01.md").read_text(encoding="utf-8")
            self.assertNotIn("example.test/web", text)
            self.assertIn("https://linehound.app/web/index.html?utm_source=l001-", text)


class Rebuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = _tree(Path(self.tmp.name), targets=big_targets(), url=HASH_URL)
        self.sales = self.root / "docs" / "sales"
        self.assertEqual(run(self.root, "build", "--batch", "1", "--date", "2026-10-02")[0], 0)

    def names(self):
        return [i["name"] for i in ob.parse_batch((self.sales / "batch_01.md").read_text(encoding="utf-8"))]

    @staticmethod
    def stable(text):
        return "\n".join(l for l in text.splitlines() if not l.startswith("- Read at "))

    def test_rebuild_keeps_the_same_leads_in_the_same_order_even_if_targets_change(self):
        before_text = (self.sales / "batch_01.md").read_text(encoding="utf-8")
        before_names, before_queue = self.names(), queue_of(self.root)
        # a better-ranked target appears; a reselection would pick it up
        path = self.sales / "targets.csv"
        old = path.read_text(encoding="utf-8")
        newrow = io.StringIO()
        csv.DictWriter(newrow, fieldnames=list(csv.DictReader(io.StringIO(old)).fieldnames),
                       lineterminator="\n").writerow(row("forum", "FNEW"))
        header, _, rest = old.partition("\n")
        path.write_text(header + "\n" + newrow.getvalue() + rest, encoding="utf-8")
        code, out, err = run(self.root, "rebuild", "--batch", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.names(), before_names)
        self.assertNotIn("FNEW", self.names())
        self.assertEqual(queue_of(self.root), before_queue)
        # only the "Read at" line and the verb differ: wording is untouched, the link is the same
        after_text = (self.sales / "batch_01.md").read_text(encoding="utf-8")
        self.assertEqual(self.stable(after_text).replace("rebuild --batch", "build --batch"),
                         self.stable(before_text))

    def test_rebuild_keeps_the_original_generation_date_for_the_followup_days(self):
        run(self.root, "rebuild", "--batch", "1")
        text = (self.sales / "batch_01.md").read_text(encoding="utf-8")
        self.assertIn("on 2026-10-02.", text)
        self.assertIn("day 3 2026-10-05, day 7 2026-10-09", text)

    def test_rebuild_refuses_once_any_item_is_marked_sent_and_writes_nothing(self):
        self.assertEqual(run(self.root, "sent", "--batch", "1", "--items", "3")[0], 0)
        before = snapshot(self.root)
        code, _, err = run(self.root, "rebuild", "--batch", "1")
        self.assertEqual(code, 2)
        self.assertIn("already marked sent", err)
        self.assertEqual(snapshot(self.root), before)

    def test_rebuild_also_refuses_for_an_item_found_in_the_pipeline_history(self):
        pipe = self.sales / "pipeline.csv"
        fields, hist = ob.read_pipeline(pipe)
        ob.append_rows(pipe, fields, ob.sent_rows([ob.parse_batch(
            (self.sales / "batch_01.md").read_text(encoding="utf-8"))[4]], 1, date(2026, 10, 2)))
        before = snapshot(self.root)
        self.assertEqual(run(self.root, "rebuild", "--batch", "1")[0], 2)
        self.assertEqual(snapshot(self.root), before)

    def test_the_guards_still_run_on_every_rebuilt_item(self):
        path = self.sales / "targets.csv"
        text = path.read_text(encoding="utf-8")
        victim = self.names()[10]
        path.write_text(text.replace("first line.", "We post a lock every night."), encoding="utf-8")
        before = snapshot(self.root)
        code, _, err = run(self.root, "rebuild", "--batch", "1")
        self.assertEqual(code, 2)
        self.assertIn("lock", err)
        self.assertIn("guard hit", err)
        self.assertEqual(snapshot(self.root), before)
        self.assertTrue(victim)

    def test_build_refuses_a_batch_file_that_exists_and_points_at_rebuild(self):
        before = snapshot(self.root)
        code, _, err = run(self.root, "build", "--batch", "1")
        self.assertEqual(code, 2)
        self.assertIn("rebuild", err)
        self.assertEqual(snapshot(self.root), before)

    def test_rebuild_of_a_legacy_file_creates_leads_in_file_order_with_tagged_links(self):
        import re
        text = (self.sales / "batch_01.md").read_text(encoding="utf-8")
        legacy = re.sub(r', "lead_id": "[^"]*"', "", text)
        legacy = re.sub(r"\?utm_source=[^#\s]*", "", legacy)
        (self.sales / "batch_01.md").write_text(legacy, encoding="utf-8")
        (self.sales / ob.QUEUE_NAME).unlink()
        self.assertEqual(run(self.root, "rebuild", "--batch", "1")[0], 0)
        rows = queue_of(self.root)
        self.assertEqual([r["person_channel"] for r in rows], self.names())
        self.assertEqual(rows[0]["lead_id"][:5], "l001-")
        new_text = (self.sales / "batch_01.md").read_text(encoding="utf-8")
        self.assertIn(f"?utm_source={rows[0]['lead_id']}&utm_medium=forum&utm_campaign=batch_01#/record-card",
                      new_text)


if __name__ == "__main__":
    unittest.main()
