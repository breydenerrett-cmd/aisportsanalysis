"""Outreach batch builder: selection, parsed text, guard, the append-only pipeline log, the v2 queue,
the private store and the reply types. Every test injects its own root, private path and clock; none
reads the real private store."""
import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts import outreach_batch as ob
from scripts import survival_dashboard as sd

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

# The real private store must stay untouched by this suite. Only its size and mtime are looked at, never its content.
REAL_PRIVATE = Path(__file__).resolve().parents[1] / "data" / "private" / "outreach_private.jsonl"


def _stat_signature():
    if not REAL_PRIVATE.exists():
        return None
    info = REAL_PRIVATE.stat()
    return (info.st_size, info.st_mtime_ns)


_REAL_PRIVATE_BEFORE = _stat_signature()


def tearDownModule():
    if _stat_signature() != _REAL_PRIVATE_BEFORE:
        raise AssertionError("a test touched the real data/private/outreach_private.jsonl")
DASH_CONFIG = {"deadline": "2026-10-31", "offers": [], "revenue": {},
               "costs_monthly": [{"item": "data", "usd": 59.0, "known": True, "class": "KEEP", "note": ""}]}

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


def run(root, *argv, now=None):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ob.main(list(argv), root=root, record_fn=lambda: RECORD,
                       now_fn=(lambda: now) if now else None)
    return code, out.getvalue(), err.getvalue()


def queue_of(root):
    return ob.read_queue(root / "docs" / "sales" / ob.QUEUE_NAME)


def snapshot(root):
    sales = root / "docs" / "sales"
    return {p.name: p.read_bytes() for p in sorted(sales.glob("*")) if p.is_file()}


def private_of(root):
    return root / "data" / "private" / "outreach_private.jsonl"


def private_lines(root):
    path = private_of(root)
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def snapshot_all(root):
    """The sales files plus the private store: a refusal must leave both byte-identical."""
    out = snapshot(root)
    if private_of(root).exists():
        out["<private>"] = private_of(root).read_bytes()
    return out


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
                keys = ob.people({"name": r["person"]})
                self.assertFalse(seen & keys, r["person"])
                seen |= keys
            self.assertEqual({r["batch"] for r in rows}, {"1", "2"})
            self.assertEqual(list(rows[0].keys()), ob.QUEUE_FIELDS)
            self.assertTrue(all(not r["sent_at"] and not r["payment_at"] for r in rows))

    def test_seed_from_legacy_batch_files_numbers_leads_in_file_order_and_is_idempotent(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_batches(tmp)
            sales = root / "docs" / "sales"
            first = [r["person"] for r in queue_of(root)]
            for name in ("batch_01.md", "batch_02.md"):      # make them look like pre-queue files
                text = (sales / name).read_text(encoding="utf-8")
                (sales / name).write_text(re.sub(r', "lead_id": "[^"]*"', "", text), encoding="utf-8")
            (sales / ob.QUEUE_NAME).unlink()
            code, out, _ = run(root, "seed")
            self.assertEqual(code, 0, out)
            rows = queue_of(root)
            self.assertEqual([r["person"] for r in rows], first)
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
            keys = ob.people({"name": r["person"]})
            self.assertFalse(seen & keys, r["person"])
            seen |= keys
        by_id = {r["lead_id"]: r for r in rows}
        for path in sorted((root / "docs" / "sales").glob("batch_*.md")):
            for item in ob.parse_batch(path.read_text(encoding="utf-8")):
                self.assertIn(item["lead_id"], by_id, item["name"])
                self.assertEqual(by_id[item["lead_id"]]["person"], item["name"])


class QueueCommands(unittest.TestCase):
    """Items 1 and 2 of batch 1 are forum threads (channel posts); 3 and 4 are creators (people)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = _tree(Path(self.tmp.name), targets=big_targets())
        run(self.root, "build", "--batch", "1", "--date", "2026-10-01")
        self.assertEqual(run(self.root, "sent", "--batch", "1", "--items", "1,2,3,4",
                             "--at", "2026-10-02T09:00:00Z")[0], 0)
        self.post, self.post2, self.a, self.b, self.unsent = [r["lead_id"] for r in queue_of(self.root)[:5]]

    def lead(self, lead_id):
        return next(r for r in queue_of(self.root) if r["lead_id"] == lead_id)

    def test_sent_stamps_the_row_and_sets_the_day_three_followup(self):
        row = self.lead(self.a)
        self.assertEqual(row["sent_at"], "2026-10-02T09:00:00Z")
        self.assertEqual(row["next_followup"], "2026-10-05")
        self.assertEqual(row["message_version"], "first_line + Variant B")
        self.assertEqual(self.lead(self.post)["message_version"], "feedback post + record link")
        self.assertEqual(self.lead(self.unsent)["sent_at"], "")

    def test_every_step_updates_one_row_and_never_adds_a_lead(self):
        pipe = self.root / "docs" / "sales" / "pipeline.csv"
        before_events = len(ob.read_pipeline(pipe)[1])
        steps = [("reply", "--type", "POSITIVE_INTEREST"), ("signup",), ("tester-access",), ("activated",),
                 ("feedback",), ("would-pay",), ("paid", "--revenue", "19.99")]
        for n, step in enumerate(steps):
            code, out, err = run(self.root, step[0], "--lead", self.a, *step[1:],
                                 "--at", f"2026-10-0{3 + n}T10:00:00Z")
            self.assertEqual(code, 0, err)
            rows = queue_of(self.root)
            self.assertEqual(len(rows), 20)                              # still 20 rows
            self.assertEqual(ob.queue_counts(rows, NOW)["leads"], 2)     # still the 2 people sent a message
        row = self.lead(self.a)
        self.assertEqual((row["reply_at"], row["reply_type"]), ("2026-10-03T10:00:00Z", "POSITIVE_INTEREST"))
        self.assertEqual(row["signup_at"], "2026-10-04T10:00:00Z")
        self.assertEqual(row["tester_access_at"], "2026-10-05T10:00:00Z")
        self.assertEqual(row["activated_at"], "2026-10-06T10:00:00Z")
        self.assertEqual(row["feedback_at"], "2026-10-07T10:00:00Z")
        self.assertEqual((row["would_pay"], row["would_pay_at"]), ("yes", "2026-10-08T10:00:00Z"))
        self.assertEqual(row["payment_at"], "2026-10-09T10:00:00Z")
        counts = ob.queue_counts(queue_of(self.root), NOW)
        self.assertEqual((counts["sent"], counts["sent_persons"], counts["replies"], counts["positive"],
                          counts["signups"], counts["activated"], counts["would_pay_yes"], counts["paid"]),
                         (4, 2, 1, 1, 1, 1, 1, 1))
        events = ob.read_pipeline(pipe)[1][before_events:]
        self.assertEqual([e["stage"] for e in events], ["replied", "signup", "tester_access", "active",
                                                        "feedback", "would_pay", "paid"])
        self.assertTrue(all(f"lead_id={self.a}" in e["notes"] for e in events))
        self.assertEqual(events[-1]["revenue"], "19.99")
        total, unknown = ob.queue_revenue(queue_of(self.root), ob.read_pipeline(pipe)[1])
        self.assertEqual((round(total, 2), unknown), (19.99, 0))

    def test_a_timestamp_is_set_once_and_never_overwritten(self):
        for step in ("signup", "tester-access"):
            self.assertEqual(run(self.root, step, "--lead", self.a, "--at", "2026-10-03T10:00:00Z")[0], 0)
            before = snapshot_all(self.root)
            code, _, err = run(self.root, step, "--lead", self.a, "--at", "2026-10-09T10:00:00Z")
            self.assertEqual(code, 2)
            self.assertIn("already recorded", err)
            self.assertEqual(snapshot_all(self.root), before)
        self.assertEqual(self.lead(self.a)["signup_at"], "2026-10-03T10:00:00Z")
        self.assertEqual(self.lead(self.a)["tester_access_at"], "2026-10-03T10:00:00Z")

    def test_later_replies_keep_the_first_time_and_follow_the_latest_type(self):
        run(self.root, "reply", "--lead", self.a, "--type", "auto", "--at", "2026-10-03T08:00:00Z")
        row = self.lead(self.a)
        self.assertEqual((row["reply_at"], row["reply_type"]), ("2026-10-03T08:00:00Z", "SPAM_OR_IRRELEVANT"))
        run(self.root, "reply", "--lead", self.a, "--type", "CURIOUS", "--at", "2026-10-04T08:00:00Z")
        row = self.lead(self.a)
        self.assertEqual((row["reply_at"], row["reply_type"]), ("2026-10-03T08:00:00Z", "CURIOUS"))
        # the same type again, with nothing new to say, writes nothing
        before = snapshot_all(self.root)
        self.assertEqual(run(self.root, "reply", "--lead", self.a, "--type", "curious")[0], 2)
        self.assertEqual(snapshot_all(self.root), before)
        # ...but a new message with the same type is kept (privately) and the queue is unchanged
        queue_before = (self.root / "docs" / "sales" / ob.QUEUE_NAME).read_bytes()
        self.assertEqual(run(self.root, "reply", "--lead", self.a, "--type", "curious", "--said", "one more thing",
                             "--at", "2026-10-06T08:00:00Z")[0], 0)
        self.assertEqual((self.root / "docs" / "sales" / ob.QUEUE_NAME).read_bytes(), queue_before)
        self.assertIn("one more thing", [e["text"] for e in private_lines(self.root)])

    def test_a_would_pay_answer_can_be_corrected_and_carries_the_price_in_notes(self):
        code, _, err = run(self.root, "would-pay", "--lead", self.a, "--price", "15", "--at", "2026-10-03T10:00:00Z")
        self.assertEqual(code, 0, err)
        row = self.lead(self.a)
        self.assertEqual((row["would_pay"], row["would_pay_at"]), ("yes", "2026-10-03T10:00:00Z"))
        self.assertEqual(row["notes"], "price_signal=15")
        self.assertEqual(run(self.root, "would-pay", "--lead", self.b, "--no", "--at", "2026-10-03T11:00:00Z")[0], 0)
        self.assertEqual(self.lead(self.b)["would_pay"], "no")
        before = snapshot_all(self.root)
        self.assertEqual(run(self.root, "would-pay", "--lead", self.a)[0], 2)     # same answer, nothing new
        self.assertEqual(snapshot_all(self.root), before)
        self.assertEqual(run(self.root, "would-pay", "--lead", self.a, "--no", "--at", "2026-10-05T10:00:00Z")[0], 0)
        row = self.lead(self.a)
        self.assertEqual((row["would_pay"], row["would_pay_at"]), ("no", "2026-10-05T10:00:00Z"))
        counts = ob.queue_counts(queue_of(self.root), NOW)
        self.assertEqual((counts["would_pay_yes"], counts["would_pay_no"]), (0, 2))

    def test_feedback_keeps_its_first_time_and_a_new_message_is_still_saved(self):
        self.assertEqual(run(self.root, "feedback", "--lead", self.a, "--said", "the card was clear",
                             "--at", "2026-10-04T10:00:00Z")[0], 0)
        self.assertEqual(run(self.root, "feedback", "--lead", self.a, "--said", "props were confusing",
                             "--at", "2026-10-06T10:00:00Z")[0], 0)
        self.assertEqual(self.lead(self.a)["feedback_at"], "2026-10-04T10:00:00Z")
        self.assertEqual([e["text"] for e in private_lines(self.root) if e["type"] == "feedback"],
                         ["the card was clear", "props were confusing"])
        self.assertEqual(run(self.root, "feedback", "--lead", self.a)[0], 2)      # nothing new at all

    def test_a_channel_post_is_not_a_human_and_cannot_reply_or_sign_up(self):
        for argv in (("reply", "--type", "CURIOUS"), ("signup",), ("tester-access",), ("activated",),
                     ("feedback", "--said", "x"), ("would-pay",), ("paid",)):
            before = snapshot_all(self.root)
            code, _, err = run(self.root, argv[0], "--lead", self.post, *argv[1:])
            self.assertEqual(code, 2, argv)
            self.assertIn("channel post", err)
            self.assertIn("add --via " + self.post, err)
            self.assertEqual(snapshot_all(self.root), before, argv)
        # sending the thread is fine, and it is a sent message but not a lead
        counts = ob.queue_counts(queue_of(self.root), NOW)
        self.assertEqual((counts["sent"], counts["leads"], counts["channel_posts_made"]), (4, 2, 2))

    def test_illegal_transitions_exit_2_and_leave_every_file_byte_identical(self):
        run(self.root, "signup", "--lead", self.a, "--at", "2026-10-03T10:00:00Z")
        cases = [
            ("reply", "--lead", self.unsent, "--type", "interested"),             # reply before sent
            ("signup", "--lead", self.unsent),
            ("paid", "--lead", self.unsent),
            ("would-pay", "--lead", self.unsent),
            ("tester-access", "--lead", self.unsent),
            ("feedback", "--lead", self.unsent, "--said", "hello"),
            ("followup", "--lead", self.unsent, "--date", "2026-10-09"),
            ("activated", "--lead", self.b),                                      # activated before signup
            ("reply", "--lead", "l999-nobody", "--type", "interested"),           # unknown lead
            ("signup", "--lead", "l999-nobody"),
            ("reply", "--lead", self.a, "--type", "ecstatic"),                    # unknown type
            ("reply", "--lead", self.a, "--type", "NO_REPLY"),                    # derived, never typed
            ("reply", "--lead", self.a),                                          # neither form
            ("signup", "--lead", self.b, "--at", "2026-10-01T00:00:00Z"),         # before it was sent
            ("signup", "--lead", self.b, "--at", "not-a-time"),
            ("paid", "--lead", self.a, "--revenue", "-5"),
            ("would-pay", "--lead", self.a, "--price", "-1"),
            ("would-pay", "--lead", self.a, "--price", "nan"),
            ("followup", "--lead", self.a, "--date", "next week"),
            ("sent", "--batch", "1", "--items", "3"),                             # already sent
            ("sent", "--batch", "1", "--items", "5,99"),                          # one bad item voids the call
            ("signup", "--lead", self.a),                                         # already signed up
        ]
        for argv in cases:
            before = snapshot_all(self.root)
            code, _, err = run(self.root, *argv)
            self.assertEqual(code, 2, (argv, err))
            self.assertIn("refused:", err)
            self.assertEqual(snapshot_all(self.root), before, argv)

    def test_followup_sets_the_next_date_and_can_be_moved(self):
        self.assertEqual(run(self.root, "followup", "--lead", self.a, "--date", "2026-10-09")[0], 0)
        self.assertEqual(self.lead(self.a)["next_followup"], "2026-10-09")
        self.assertEqual(run(self.root, "followup", "--lead", self.a, "--date", "2026-10-12")[0], 0)
        self.assertEqual(self.lead(self.a)["next_followup"], "2026-10-12")
        self.assertEqual(len(queue_of(self.root)), 20)

    def test_a_lead_can_be_named_by_its_person(self):
        name = self.lead(self.a)["person"]
        self.assertEqual(run(self.root, "signup", "--target", name.lower(), "--at", "2026-10-03T10:00:00Z")[0], 0)
        self.assertTrue(self.lead(self.a)["signup_at"])

    def test_milestones_print_the_first_timestamp_and_lead_of_each_step_or_not_yet(self):
        code, out, _ = run(self.root, "milestones")
        self.assertEqual(code, 0)
        self.assertIn(f"First message sent: 2026-10-02T09:00:00Z ({self.post})", out)
        for label in ("First reply", "First positive reply", "First signup", "First tester access",
                      "First active tester", "First feedback", "First would-pay", "First payment"):
            self.assertRegex(out, rf"{label}[^\n]*: not yet")
        run(self.root, "reply", "--lead", self.b, "--type", "SPAM_OR_IRRELEVANT", "--at", "2026-10-02T09:30:00Z")
        run(self.root, "reply", "--lead", self.a, "--type", "CURIOUS", "--at", "2026-10-03T12:00:00Z")
        run(self.root, "reply", "--lead", self.a, "--type", "WOULD_PAY", "--at", "2026-10-03T13:00:00Z")
        run(self.root, "signup", "--lead", self.a, "--at", "2026-10-05T12:00:00Z")
        run(self.root, "signup", "--lead", self.b, "--at", "2026-10-04T12:00:00Z")
        run(self.root, "tester-access", "--lead", self.b, "--at", "2026-10-04T13:00:00Z")
        run(self.root, "activated", "--lead", self.b, "--at", "2026-10-04T14:00:00Z")
        run(self.root, "feedback", "--lead", self.b, "--at", "2026-10-06T14:00:00Z")
        run(self.root, "would-pay", "--lead", self.a, "--at", "2026-10-07T14:00:00Z")
        run(self.root, "would-pay", "--lead", self.b, "--no", "--at", "2026-10-06T14:00:00Z")
        found = ob.milestones(queue_of(self.root))
        self.assertEqual(found["first_sent"], ("2026-10-02T09:00:00Z", self.post))
        self.assertEqual(found["first_reply"], ("2026-10-02T09:30:00Z", self.b))
        self.assertEqual(found["first_positive"], ("2026-10-03T12:00:00Z", self.a))   # the spam reply never counts
        self.assertEqual(found["first_signup"], ("2026-10-04T12:00:00Z", self.b))
        self.assertEqual(found["first_tester_access"], ("2026-10-04T13:00:00Z", self.b))
        self.assertEqual(found["first_active"], ("2026-10-04T14:00:00Z", self.b))
        self.assertEqual(found["first_feedback"], ("2026-10-06T14:00:00Z", self.b))
        self.assertEqual(found["first_would_pay"], ("2026-10-07T14:00:00Z", self.a))  # b said no
        self.assertIsNone(found["first_payment"])
        out = run(self.root, "milestones")[1]
        self.assertIn(f"First signup: 2026-10-04T12:00:00Z ({self.b})", out)
        self.assertIn("First payment: not yet", out)

    def test_the_legacy_stage_form_still_works_and_says_it_left_the_queue_alone(self):
        name = self.lead(self.a)["person"]
        before = (self.root / "docs" / "sales" / ob.QUEUE_NAME).read_bytes()
        code, out, _ = run(self.root, "reply", "--target", name, "--stage", "replied", "--date", "2026-10-03")
        self.assertEqual(code, 0)
        self.assertIn("queue", out)
        self.assertEqual((self.root / "docs" / "sales" / ob.QUEUE_NAME).read_bytes(), before)

    def test_the_legacy_stage_form_refuses_said_because_it_would_be_dropped(self):
        name = self.lead(self.a)["person"]
        before = snapshot_all(self.root)
        code, _, err = run(self.root, "reply", "--target", name, "--stage", "replied", "--said", "words")
        self.assertEqual(code, 2)
        self.assertIn("--said", err)
        self.assertEqual(snapshot_all(self.root), before)

    def test_the_old_classification_flag_and_words_still_work(self):
        for flag, word, expected in (("--classification", "interested", "POSITIVE_INTEREST"),
                                     ("--type", "Question", "CURIOUS")):
            code, _, err = run(self.root, "reply", "--lead", self.b, flag, word, "--at", "2026-10-03T10:00:00Z")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.lead(self.b)["reply_type"], expected)
        for word, expected in (("not_interested", "NOT_INTERESTED"), ("auto", "SPAM_OR_IRRELEVANT"),
                               ("hostile", "TRUST_OBJECTION"), ("price_objection", "PRICE_OBJECTION")):
            self.assertEqual(ob.parse_reply_type(word), expected)


class ReplyTypes(unittest.TestCase):
    EXACT = ("POSITIVE_INTEREST", "CURIOUS", "SIGNED_UP", "ACTIVE_TESTER", "WOULD_PAY", "PRICE_OBJECTION",
             "TRUST_OBJECTION", "PRODUCT_CONFUSION", "NOT_INTERESTED", "NO_REPLY", "SPAM_OR_IRRELEVANT")

    def test_the_eleven_exact_strings(self):
        self.assertEqual(ob.REPLY_TYPES, self.EXACT)
        self.assertEqual(ob.POSITIVE_TYPES, ("POSITIVE_INTEREST", "SIGNED_UP", "ACTIVE_TESTER", "WOULD_PAY"))

    def test_any_case_and_every_typeable_type_is_accepted(self):
        for t in self.EXACT:
            if t == "NO_REPLY":
                continue
            self.assertEqual(ob.parse_reply_type(t), t)
            self.assertEqual(ob.parse_reply_type(t.lower()), t)
            self.assertEqual(ob.parse_reply_type(t.title().replace("_", "-")), t)

    def test_no_reply_is_derived_so_it_cannot_be_typed_and_unknown_is_refused(self):
        with self.assertRaises(ob.OutreachError) as cm:
            ob.parse_reply_type("no_reply")
        self.assertIn("worked out by itself", str(cm.exception))
        self.assertEqual(ob.parse_reply_type("NO_REPLY", allow_no_reply=True), "NO_REPLY")
        for bad in ("", "ecstatic", "positive"):
            with self.assertRaises(ob.OutreachError, msg=bad):
                ob.parse_reply_type(bad)


class NoReplyIsDerived(unittest.TestCase):
    SENT = "2026-10-02T09:00:00Z"

    def row(self, **kw):
        base = {f: "" for f in ob.QUEUE_FIELDS}
        base.update({"lead_id": "l001-x", "kind": "person", "person": "X", "channel": "creator",
                     "sent_at": self.SENT})
        base.update(kw)
        return base

    def test_more_than_seven_days_after_a_send_with_no_reply_reads_as_no_reply(self):
        sent = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
        row = self.row()
        self.assertEqual(ob.effective_reply_type(row, sent + timedelta(days=7)), "")             # exactly 7 days
        self.assertEqual(ob.effective_reply_type(row, sent + timedelta(days=7, seconds=1)), "NO_REPLY")
        self.assertEqual(ob.effective_reply_type(row, sent + timedelta(days=1)), "")

    def test_a_reply_a_missing_send_or_a_channel_post_is_never_no_reply(self):
        late = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.assertEqual(ob.effective_reply_type(self.row(reply_at="2026-10-03T00:00:00Z"), late), "")
        self.assertEqual(ob.effective_reply_type(self.row(reply_at="2026-10-03T00:00:00Z",
                                                          reply_type="CURIOUS"), late), "CURIOUS")
        self.assertEqual(ob.effective_reply_type(self.row(sent_at=""), late), "")
        self.assertEqual(ob.effective_reply_type(self.row(kind="channel_post"), late), "")

    def test_status_reports_it_without_anyone_typing_it_and_never_writes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp), targets=big_targets())
            run(root, "build", "--batch", "1", "--date", "2026-10-01")
            run(root, "sent", "--batch", "1", "--items", "3,4", "--at", self.SENT)
            run(root, "reply", "--lead", queue_of(root)[3]["lead_id"], "--type", "CURIOUS",
                "--at", "2026-10-03T00:00:00Z")
            early = run(root, "status", now=datetime(2026, 10, 5, tzinfo=timezone.utc))[1]
            self.assertIn("NO_REPLY: 0", early)
            late = run(root, "status", now=datetime(2026, 10, 12, tzinfo=timezone.utc))[1]
            self.assertIn("NO_REPLY: 1", late)
            self.assertIn("CURIOUS: 1", late)
            self.assertEqual({r["reply_type"] for r in queue_of(root)}, {"", "CURIOUS"})


class StatusAndGroups(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = _tree(Path(self.tmp.name), targets=big_targets())
        run(self.root, "build", "--batch", "1", "--date", "2026-10-01")
        rows = queue_of(self.root)
        self.ids = [r["lead_id"] for r in rows]

    def test_status_lists_only_leads_with_activity_and_every_type_with_its_zero(self):
        out = run(self.root, "status")[1]
        self.assertIn("no lead has any activity yet", out)
        for t in ob.REPLY_TYPES:
            self.assertIn(f"{t}: 0", out)
        self.assertIn("UNCLASSIFIED: 0", out)
        run(self.root, "sent", "--batch", "1", "--items", "3", "--at", "2026-10-02T09:00:00Z")
        run(self.root, "reply", "--lead", self.ids[2], "--type", "PRICE_OBJECTION", "--at", "2026-10-03T09:00:00Z")
        out = run(self.root, "status", now=datetime(2026, 10, 4, tzinfo=timezone.utc))[1]
        lines = [l for l in out.splitlines() if l.startswith("l0")]
        self.assertEqual(len(lines), 1)
        self.assertIn(self.ids[2], lines[0])
        self.assertIn("reply PRICE_OBJECTION", lines[0])
        self.assertIn("PRICE_OBJECTION: 1", out)
        self.assertIn("CURIOUS: 0", out)

    def test_set_group_then_next_group_walks_the_groups_in_order(self):
        self.assertIn("No send groups assigned", run(self.root, "next-group")[1])
        a, b, c = self.ids[2], self.ids[3], self.ids[4]
        self.assertEqual(run(self.root, "set-group", "--leads", f"{c},{a}", "--group", "2")[0], 0)
        self.assertEqual(run(self.root, "set-group", "--leads", f"{a}", "--group", "1")[0], 0)   # regrouped
        self.assertEqual(run(self.root, "set-group", "--leads", f"{b}", "--group", "1")[0], 0)
        rows = {r["lead_id"]: r for r in queue_of(self.root)}
        self.assertEqual((rows[a]["send_group"], rows[b]["send_group"], rows[c]["send_group"]), ("1", "1", "2"))
        out = run(self.root, "next-group")[1]
        self.assertIn("Send group 1: 2 of 2", out)
        self.assertIn(f"- {a} | {rows[a]['person']} | creator", out)
        self.assertIn("docs/sales/batch_01.md, item 3", out)
        self.assertIn("python scripts/outreach_batch.py sent --batch 1 --items 3", out)
        self.assertIn("sent --batch 1 --items 4", out)
        self.assertIn("--items 3,4", out)                       # the whole group in one command
        self.assertNotIn(c, out)
        run(self.root, "sent", "--batch", "1", "--items", "3,4", "--at", "2026-10-02T09:00:00Z")
        out = run(self.root, "next-group")[1]
        self.assertIn("Send group 2: 1 of 1", out)
        self.assertIn(f"- {c} |", out)
        self.assertIn("sent --batch 1 --items 5", out)
        self.assertNotIn(a, out)
        run(self.root, "sent", "--batch", "1", "--items", "5", "--at", "2026-10-02T09:00:00Z")
        self.assertIn("has been sent", run(self.root, "next-group")[1])

    def test_set_group_refuses_unknown_duplicate_empty_and_bad_group_and_writes_nothing(self):
        for argv in (("--leads", f"{self.ids[2]},l999-nobody", "--group", "1"),
                     ("--leads", f"{self.ids[2]},{self.ids[2]}", "--group", "1"),
                     ("--leads", " , ", "--group", "1"),
                     ("--leads", self.ids[2], "--group", "0")):
            before = snapshot_all(self.root)
            code, _, err = run(self.root, "set-group", *argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("refused:", err)
            self.assertEqual(snapshot_all(self.root), before)

    def test_next_group_says_so_when_a_lead_is_in_no_batch_file(self):
        rows = queue_of(self.root)
        rows.append(dict(rows[2], lead_id="l099-p", person="l099-p", send_group="1"))
        ob.write_queue(self.root / "docs" / "sales" / ob.QUEUE_NAME, rows)
        out = run(self.root, "next-group")[1]
        self.assertIn("- l099-p |", out)
        self.assertIn("no batch file lists this lead", out)


class PrivateStore(unittest.TestCase):
    """The repo is public: what people wrote and who they are never reaches a tracked file."""

    SAID = "this is a very private sentence about my cousin Zebediah"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = _tree(Path(self.tmp.name), targets=big_targets())
        run(self.root, "build", "--batch", "1", "--date", "2026-10-01")
        run(self.root, "sent", "--batch", "1", "--items", "3,4", "--at", "2026-10-02T09:00:00Z")
        self.a, self.b = [r["lead_id"] for r in queue_of(self.root)[2:4]]

    def tracked_text(self):
        return "\n".join(p.read_text(encoding="utf-8") for p in sorted((self.root / "docs").rglob("*")) if p.is_file())

    def test_reply_text_goes_to_the_private_file_only(self):
        code, out, err = run(self.root, "reply", "--lead", self.a, "--type", "CURIOUS", "--said", self.SAID,
                             "--by", "ai", "--at", "2026-10-03T10:00:00Z")
        self.assertEqual(code, 0, err)
        self.assertNotIn("Zebediah", out + err + self.tracked_text())
        lines = private_lines(self.root)
        self.assertEqual([(e["lead_id"], e["type"], e["text"], e["by"]) for e in lines],
                         [(self.a, "reply", self.SAID, "ai"), (self.a, "classification", "CURIOUS", "ai")])
        self.assertTrue(all(set(e) == {"lead_id", "at", "type", "text", "by"} for e in lines))
        self.assertEqual(lines[0]["at"], "2026-10-03T10:00:00Z")

    def test_the_store_is_append_only_and_a_reclassification_changes_only_reply_type(self):
        run(self.root, "reply", "--lead", self.a, "--type", "CURIOUS", "--said", self.SAID, "--at", "2026-10-03T10:00:00Z")
        store = private_of(self.root).read_bytes()
        before_row = next(r for r in queue_of(self.root) if r["lead_id"] == self.a)
        run(self.root, "reply", "--lead", self.a, "--type", "TRUST_OBJECTION", "--at", "2026-10-04T10:00:00Z")
        after_row = next(r for r in queue_of(self.root) if r["lead_id"] == self.a)
        self.assertEqual({k for k in before_row if before_row[k] != after_row[k]}, {"reply_type"})
        self.assertEqual(after_row["reply_type"], "TRUST_OBJECTION")
        grown = private_of(self.root).read_bytes()
        self.assertTrue(grown.startswith(store))                       # earlier bytes untouched
        added = [json.loads(l) for l in grown[len(store):].decode().splitlines()]
        self.assertEqual([(e["type"], e["text"]) for e in added], [("classification", "TRUST_OBJECTION")])
        # the verbatim message is still there, unedited
        self.assertEqual(private_lines(self.root)[0]["text"], self.SAID)

    def test_the_pipeline_and_the_queue_hold_no_verbatim_text_or_handle(self):
        run(self.root, "reply", "--lead", self.a, "--type", "CURIOUS", "--said", self.SAID)
        run(self.root, "add", "--via", self.a, "--channel", "discord", "--handle", "@Zebediah_Cousin",
            "--type", "CURIOUS", "--said", "my cousin Zebediah says hi")
        run(self.root, "alias", "--lead", "l021-p", "--handle", "zeb@example.test")
        blob = self.tracked_text()
        for needle in ("Zebediah", "zebediah", "cousin", "zeb@example"):
            self.assertNotIn(needle, blob)

    def test_the_path_comes_from_an_argument_then_the_environment_then_the_root(self):
        root = Path(self.tmp.name)
        self.assertEqual(ob.private_path(root), root / "data" / "private" / "outreach_private.jsonl")
        with mock.patch.dict(os.environ, {ob.PRIVATE_ENV: str(root / "elsewhere.jsonl")}):
            self.assertEqual(ob.private_path(root), root / "elsewhere.jsonl")
            self.assertEqual(ob.private_path(root, root / "arg.jsonl"), root / "arg.jsonl")
            with redirect_stdout(io.StringIO()):
                code = ob.main(["reply", "--lead", self.a, "--type", "CURIOUS", "--said", "via env"], root=root)
        self.assertEqual(code, 0)
        self.assertTrue((root / "elsewhere.jsonl").exists())
        self.assertFalse(private_of(self.root).exists())
        arg = root / "arg.jsonl"
        with redirect_stdout(io.StringIO()):
            ob.main(["feedback", "--lead", self.a, "--said", "via argument"], root=root, private_path_override=arg)
        self.assertIn("via argument", arg.read_text(encoding="utf-8"))

    def test_note_and_sport_refuse_handles_emails_links_and_known_identities(self):
        run(self.root, "add", "--via", self.a, "--channel", "discord", "--handle", "SecretName99", "--type", "CURIOUS")
        for argv in (("followup", "--lead", self.a, "--date", "2026-10-09", "--note", "ping @someone"),
                     ("followup", "--lead", self.a, "--date", "2026-10-09", "--note", "see http://x.test"),
                     ("followup", "--lead", self.a, "--date", "2026-10-09", "--note", "it was secret name 99 again"),
                     ("add", "--via", self.a, "--channel", "x", "--sport", "mlb, @handle"),
                     ("signup", "--lead", self.a, "--note", "mail me at a@b.test"),
                     ("sent", "--batch", "1", "--items", "5", "--note", "to @someone")):
            before = snapshot_all(self.root)
            code, _, err = run(self.root, *argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("tracked file", err)
            self.assertEqual(snapshot_all(self.root), before, argv)
        self.assertEqual(run(self.root, "followup", "--lead", self.a, "--date", "2026-10-09",
                             "--note", "asked for a call")[0], 0)

    def test_a_damaged_store_is_a_refusal_never_a_silent_skip(self):
        run(self.root, "add", "--via", self.a, "--channel", "discord", "--handle", "someone")
        with private_of(self.root).open("a", encoding="utf-8") as handle:
            handle.write("not json at all\n")
        before = snapshot_all(self.root)
        code, _, err = run(self.root, "add", "--via", self.a, "--channel", "discord", "--handle", "someoneelse")
        self.assertEqual(code, 2)
        self.assertIn("line 2", err)
        self.assertEqual(snapshot_all(self.root), before)

    def test_entries_are_validated_and_a_missing_final_newline_is_repaired_without_rewriting(self):
        with self.assertRaises(ob.OutreachError):
            ob.private_entry("l1-x", "t", "gossip", "x")
        with self.assertRaises(ob.OutreachError):
            ob.private_entry("l1-x", "t", "reply", "x", by="robot")
        path = Path(self.tmp.name) / "p.jsonl"
        path.write_bytes(b'{"lead_id": "l1-x", "at": "t", "type": "note", "text": "a", "by": "owner"}')
        ob.append_private(path, [ob.private_entry("l2-x", "t", "note", "b")])
        self.assertEqual(len(ob.read_private(path)), 2)
        self.assertTrue(path.read_bytes().startswith(b'{"lead_id": "l1-x"'))

    def test_the_real_store_is_gitignored_and_no_test_here_reads_it(self):
        ignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("data/private/", [l.strip() for l in ignore])
        self.assertEqual(ob.PRIVATE_REL.as_posix(), "data/private/outreach_private.jsonl")
        self.assertTrue(str(private_of(self.root)).startswith(self.tmp.name))


class AddAndAlias(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = _tree(Path(self.tmp.name), targets=big_targets())
        run(self.root, "build", "--batch", "1", "--date", "2026-10-01")
        rows = queue_of(self.root)
        self.post, self.post2, self.a = [r["lead_id"] for r in rows[:3]]

    def lead(self, lead_id):
        return next(r for r in queue_of(self.root) if r["lead_id"] == lead_id)

    def test_add_makes_a_person_with_an_id_that_holds_no_personal_data(self):
        code, out, err = run(self.root, "add", "--via", self.post, "--channel", "Discord",
                             "--handle", "@Some_User", "--sport", "MLB props", "--type", "curious",
                             "--said", "hi, how does it work?", "--at", "2026-10-03T10:00:00Z")
        self.assertEqual(code, 0, err)
        rows = queue_of(self.root)
        self.assertEqual(len(rows), 21)
        new = rows[-1]
        self.assertEqual(new["lead_id"], "l021-p")
        self.assertRegex(new["lead_id"], r"^l\d{3}-p$")
        self.assertEqual((new["kind"], new["channel"], new["campaign"], new["batch"], new["via_lead"]),
                         ("person", "discord", "batch_01", "1", self.post))
        self.assertEqual((new["person"], new["sport_interest"], new["reply_at"], new["reply_type"], new["sent_at"]),
                         ("l021-p", "MLB props", "2026-10-03T10:00:00Z", "CURIOUS", ""))
        self.assertEqual([(e["type"], e["text"]) for e in private_lines(self.root)],
                         [("identity", "@Some_User"), ("reply", "hi, how does it work?"),
                          ("classification", "CURIOUS")])
        self.assertNotIn("Some_User", out + (self.root / "docs" / "sales" / ob.QUEUE_NAME).read_text(encoding="utf-8"))
        # they count as a lead and a reply, but not toward the reply RATE (we never messaged them)
        counts = ob.queue_counts(rows, NOW)
        self.assertEqual((counts["leads"], counts["replies"], counts["sent_persons"], counts["replied_after_sent"]),
                         (1, 1, 0, 0))
        # and the next one gets the next number
        run(self.root, "add", "--via", self.post, "--channel", "discord", "--handle", "other")
        self.assertEqual(queue_of(self.root)[-1]["lead_id"], "l022-p")

    def test_add_for_a_handle_already_known_under_another_channel_is_refused(self):
        self.assertEqual(run(self.root, "add", "--via", self.post, "--channel", "discord",
                             "--handle", "@Some_User")[0], 0)
        for handle in ("some_user", "@SOME_USER", "  @ Some _User  "):
            before = snapshot_all(self.root)
            code, _, err = run(self.root, "add", "--via", self.post2, "--channel", "x", "--handle", handle)
            self.assertEqual(code, 2, handle)
            self.assertIn("l021-p", err)                 # names the lead that already has the handle
            self.assertIn("alias", err)                  # and says what to do instead
            self.assertEqual(snapshot_all(self.root), before, handle)
        self.assertEqual(len(queue_of(self.root)), 21)
        # the dashboard still counts one human
        text = sd.render(DASH_CONFIG, date(2026, 10, 4), "2026-10-04 00:00Z",
                         queue_rows=queue_of(self.root), pipeline_rows=[], record=[])
        self.assertIn("| UNIQUE LEADS | 1 |", text)

    def test_an_alias_is_the_same_human_so_it_collides_too(self):
        run(self.root, "add", "--via", self.post, "--channel", "discord", "--handle", "first_handle")
        self.assertEqual(run(self.root, "alias", "--lead", "l021-p", "--handle", "Same.Person@Example.test")[0], 0)
        before = snapshot_all(self.root)
        code, _, err = run(self.root, "add", "--via", self.post2, "--channel", "email",
                           "--handle", "same.person@example.test")
        self.assertEqual(code, 2)
        self.assertIn("l021-p", err)
        self.assertEqual(snapshot_all(self.root), before)

    def test_alias_refuses_a_handle_that_belongs_to_another_lead_or_to_this_one(self):
        run(self.root, "add", "--via", self.post, "--channel", "discord", "--handle", "alpha")
        run(self.root, "add", "--via", self.post, "--channel", "discord", "--handle", "bravo")
        before = snapshot_all(self.root)
        code, _, err = run(self.root, "alias", "--lead", "l022-p", "--handle", "@Alpha")
        self.assertEqual(code, 2)
        self.assertIn("l021-p", err)
        self.assertEqual(run(self.root, "alias", "--lead", "l021-p", "--handle", "alpha")[0], 2)    # its own
        self.assertEqual(run(self.root, "alias", "--lead", "l999-nobody", "--handle", "zulu")[0], 2)
        self.assertEqual(run(self.root, "alias", "--lead", self.post, "--handle", "zulu")[0], 2)    # a thread
        self.assertEqual(run(self.root, "alias", "--lead", "l021-p", "--handle", "  @  ")[0], 2)
        self.assertEqual(snapshot_all(self.root), before)

    def test_a_handle_already_public_in_the_queue_is_the_same_human(self):
        rows = queue_of(self.root)
        rows[2]["person"] = "Joseph Buchdahl (@12Xpert)"
        ob.write_queue(self.root / "docs" / "sales" / ob.QUEUE_NAME, rows)
        before = snapshot_all(self.root)
        code, _, err = run(self.root, "add", "--via", self.post, "--channel", "x", "--handle", "12xpert")
        self.assertEqual(code, 2)
        self.assertIn(self.a, err)
        self.assertEqual(snapshot_all(self.root), before)

    def test_someone_who_wrote_in_on_their_own_has_no_via_lead(self):
        code, out, err = run(self.root, "add", "--channel", "email", "--handle", "walkin@example.test",
                             "--type", "POSITIVE_INTEREST", "--at", "2026-10-03T10:00:00Z")
        self.assertEqual(code, 0, err)
        new = queue_of(self.root)[-1]
        self.assertEqual((new["via_lead"], new["campaign"], new["batch"]), ("", "organic", ""))
        self.assertEqual(run(self.root, "signup", "--lead", new["lead_id"], "--at", "2026-10-04T10:00:00Z")[0], 0)

    def test_an_added_person_can_be_logged_against_without_ever_having_been_sent_a_message(self):
        run(self.root, "add", "--via", self.post, "--channel", "discord", "--handle", "someone", "--type", "CURIOUS",
            "--at", "2026-10-03T10:00:00Z")
        for argv in (("reply", "--type", "WOULD_PAY"), ("signup",), ("tester-access",), ("activated",),
                     ("feedback", "--said", "nice"), ("would-pay", "--price", "10"), ("paid", "--revenue", "10")):
            code, _, err = run(self.root, argv[0], "--lead", "l021-p", *argv[1:], "--at", "2026-10-04T10:00:00Z")
            self.assertEqual(code, 0, (argv, err))
        row = self.lead("l021-p")
        self.assertEqual((row["reply_at"], row["reply_type"]), ("2026-10-03T10:00:00Z", "WOULD_PAY"))
        self.assertTrue(row["signup_at"] and row["payment_at"])
        # a person who was never sent a message cannot be earlier than their own reply for a send event
        self.assertEqual(run(self.root, "followup", "--lead", "l021-p", "--date", "2026-10-09")[0], 0)

    def test_add_validates_channel_type_and_the_via_lead(self):
        for argv in (("--via", self.post, "--channel", "bob#1234"),         # a handle where a platform goes
                     ("--via", self.post, "--channel", "@bob"),
                     ("--via", self.post, "--channel", "x" * 30),
                     ("--via", self.post, "--channel", "x", "--type", "NO_REPLY"),
                     ("--via", self.post, "--channel", "x", "--type", "ecstatic"),
                     ("--via", "l999-nobody", "--channel", "x"),
                     ("--via", self.post, "--channel", "x", "--handle", "")):
            before = snapshot_all(self.root)
            code, _, err = run(self.root, "add", *argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("refused:", err)
            self.assertEqual(snapshot_all(self.root), before, argv)

    def test_add_without_a_handle_warns_that_the_duplicate_check_could_not_run(self):
        code, out, _ = run(self.root, "add", "--via", self.post, "--channel", "discord")
        self.assertEqual(code, 0)
        self.assertIn("duplicate-human check could not run", out)
        self.assertIn("reply --lead l021-p --type", out)
        self.assertEqual(private_lines(self.root), [])

    def test_the_audit_trail_row_for_an_add_has_ids_and_types_only(self):
        run(self.root, "add", "--via", self.post, "--channel", "discord", "--handle", "someone", "--type", "CURIOUS",
            "--said", "secret words", "--at", "2026-10-03T10:00:00Z")
        events = ob.read_pipeline(self.root / "docs" / "sales" / "pipeline.csv")[1]
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertEqual((e["stage"], e["target"], e["source"], e["campaign"]), ("replied", "l021-p", "discord", "batch_01"))
        self.assertIn("lead_id=l021-p", e["notes"])
        self.assertIn("added via " + self.post, e["notes"])
        self.assertNotIn("secret", str(e))
        self.assertNotIn("someone", str(e))


class MigrationFromV1(unittest.TestCase):
    OLD = ob.OLD_QUEUE_FIELDS

    def write_old(self, root, rows):
        path = root / "docs" / "sales" / ob.QUEUE_NAME
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.OLD, lineterminator="\n", restval="")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def old_row(self, n, source, **kw):
        row = {"lead_id": f"l{n:03d}-lead-{n}", "person_channel": f"Lead {n} (@h{n})", "source": source,
               "sport_interest": "MLB", "message_version": "v", "batch": "2"}
        row.update(kw)
        return row

    def test_the_v1_header_is_read_as_v2_with_the_documented_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp))
            path = self.write_old(root, [
                self.old_row(1, "forum"),
                self.old_row(2, "creator", sent_at="2026-10-02T09:00:00Z", reply_at="2026-10-03T09:00:00Z",
                             reply_classification="interested", would_pay_at="2026-10-04T09:00:00Z", notes="n"),
                self.old_row(3, "discord_server", reply_classification="auto", batch=""),
                self.old_row(4, "x_account", reply_classification="hostile")])
            rows = ob.read_queue(path)
            self.assertEqual([r["lead_id"] for r in rows], ["l001-lead-1", "l002-lead-2", "l003-lead-3", "l004-lead-4"])
            self.assertTrue(all(list(r) == ob.QUEUE_FIELDS for r in rows))
            self.assertEqual([r["kind"] for r in rows], ["channel_post", "person", "person", "person"])
            self.assertEqual([r["channel"] for r in rows], ["forum", "creator", "discord_server", "x_account"])
            self.assertEqual([r["campaign"] for r in rows], ["batch_02", "batch_02", "", "batch_02"])
            self.assertEqual(rows[1]["person"], "Lead 2 (@h2)")
            self.assertEqual((rows[1]["reply_type"], rows[1]["would_pay"], rows[1]["would_pay_at"], rows[1]["notes"]),
                             ("POSITIVE_INTEREST", "yes", "2026-10-04T09:00:00Z", "n"))
            self.assertEqual((rows[2]["reply_type"], rows[3]["reply_type"]), ("SPAM_OR_IRRELEVANT", "TRUST_OBJECTION"))
            self.assertEqual(rows[0]["would_pay"], "")
            self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], ",".join(self.OLD))   # not rewritten by a read

    def test_the_first_command_that_saves_writes_v2_and_keeps_every_lead_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _tree(Path(tmp))
            path = self.write_old(root, [self.old_row(1, "creator", sent_at="2026-10-02T09:00:00Z")])
            self.assertEqual(run(root, "reply", "--lead", "l001-lead-1", "--type", "CURIOUS",
                                 "--at", "2026-10-03T09:00:00Z")[0], 0)
            self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], ",".join(ob.QUEUE_FIELDS))
            row = queue_of(root)[0]
            self.assertEqual((row["lead_id"], row["reply_type"]), ("l001-lead-1", "CURIOUS"))

    def test_a_header_that_is_neither_version_and_a_bad_kind_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.csv"
            path.write_text("lead_id,person\nl001-x,X\n", encoding="utf-8")
            with self.assertRaises(ob.OutreachError):
                ob.read_queue(path)
            ob.write_queue(path, [dict({f: "" for f in ob.QUEUE_FIELDS}, lead_id="l001-x", kind="human")])
            with self.assertRaises(ob.OutreachError) as cm:
                ob.read_queue(path)
            self.assertIn("kind", str(cm.exception))

    def test_the_committed_queue_is_v2_with_the_migrated_values(self):
        """Reads the real (public) queue on purpose: the live utm_source ids must survive."""
        root = Path(__file__).resolve().parents[1]
        path = root / "docs" / "sales" / ob.QUEUE_NAME
        self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], ",".join(ob.QUEUE_FIELDS))
        rows = ob.read_queue(path)
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[0]["lead_id"], "l001-covers-website-promotions-forum")
        self.assertEqual({r["kind"] for r in rows if r["channel"] == "forum"}, {"channel_post"})
        self.assertEqual({r["kind"] for r in rows if r["channel"] != "forum"}, {"person"})
        self.assertEqual({r["campaign"] for r in rows}, {"batch_01", "batch_02"})
        for r in rows:
            self.assertEqual(r["campaign"], f"batch_{int(r['batch']):02d}")
            self.assertEqual(r["via_lead"], "")


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
        self.assertEqual([r["person"] for r in rows], self.names())
        self.assertEqual(rows[0]["lead_id"][:5], "l001-")
        new_text = (self.sales / "batch_01.md").read_text(encoding="utf-8")
        self.assertIn(f"?utm_source={rows[0]['lead_id']}&utm_medium=forum&utm_campaign=batch_01#/record-card",
                      new_text)


if __name__ == "__main__":
    unittest.main()
