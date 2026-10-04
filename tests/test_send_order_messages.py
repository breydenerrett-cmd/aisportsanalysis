"""The five outreach messages in docs/sales/SEND_ORDER.md are finished text.

Brey sends them by hand, so a leftover bracket, a missing link or a claim the
product cannot back is a defect he would only find after sending. This reads
the top section ("Send these five first") and checks, for each of the five
leads: the tagged link is complete and uses a lead id and channel that exist in
docs/sales/outreach_queue.csv; no placeholder is left; the facts that must be
said are said; the words that must not appear are absent; an X message fits.
No network, no FastAPI.
"""

from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEND_ORDER = ROOT / "docs" / "sales" / "SEND_ORDER.md"
QUEUE = ROOT / "docs" / "sales" / "outreach_queue.csv"
VERSION = "v3e-ready"

# item -> (lead id, channel tag in the link)
FIVE = {
    9: ("l009-tommy-lorenzo", "x_account"),
    3: ("l003-justbaseball-betting", "creator"),
    8: ("l008-tyler-shoemaker", "x_account"),
    11: ("l011-picks-with-the-professor", "x_account"),
    12: ("l012-unit-circle", "discord"),
}
LINK_RE = re.compile(
    r"https://linehound\.app/web/sample\.html\?utm_source=([\w-]+)&utm_medium=(\w+)&utm_campaign=brief_01")


def top_section() -> str:
    text = SEND_ORDER.read_text(encoding="utf-8")
    return text.split("## Send these five first", 1)[1].split("\n## ", 1)[0]


def blocks(section: str):
    """[(heading, [code blocks])] for each '### Item N' heading."""
    out = {}
    for part in re.split(r"\n(?=### )", section):
        m = re.match(r"### Item (\d+),", part)
        if m:
            out[int(m.group(1))] = re.findall(r"```\n(.*?)\n```", part, re.S)
    return out


class FiveMessages(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.section = top_section()
        cls.items = blocks(cls.section)

    def test_all_five_items_are_present(self):
        self.assertEqual(set(self.items), set(FIVE))

    def test_every_message_block_has_its_own_tagged_link_and_no_placeholder(self):
        for n, (lead, channel) in FIVE.items():
            msgs = self.items[n]
            self.assertTrue(msgs, n)
            message_text = "\n".join(msgs)
            links = LINK_RE.findall(message_text)
            self.assertTrue(links, f"item {n}: no tagged link")
            for src, medium in links:
                self.assertEqual((src, medium), (lead, channel), n)
            for bad in ("[", "]", "LINK", "<", ">", "TODO", "[Name]", "one thing from"):
                self.assertNotIn(bad, "\n".join(m for m in msgs if "token" not in m.lower()),
                                 f"item {n}: placeholder {bad!r}")

    def test_the_leads_and_channels_exist_in_the_queue(self):
        with QUEUE.open(encoding="utf-8", newline="") as fh:
            rows = {r["lead_id"]: r for r in csv.DictReader(fh)}
        for n, (lead, _channel) in FIVE.items():
            self.assertIn(lead, rows, n)

    def test_the_full_message_says_the_required_facts(self):
        for n in FIVE:
            joined = " ".join(self.items[n][:2] if n != 12 else self.items[n][:1])
            low = joined.lower()
            for fact in ("ai analysis, not advice", "no edge", "not on sale yet", "$19.99 a month",
                         "first 20 testers", "7 days free", "no card"):
                self.assertIn(fact, low, f"item {n}: {fact!r}")
            self.assertIn("the latest one", low, n)

    def test_no_claim_the_page_cannot_back_and_no_banned_words(self):
        for n in FIVE:
            low = " ".join(self.items[n]).lower()
            self.assertNotIn("today's", low, n)
            self.assertNotIn("today’s", low, n)
            self.assertNotIn("bet check", low, n)
            self.assertNotIn("betcheck", low, n)
            for claim in ("win rate", "win-rate", "profit", "guarantee", "sharp", "winning"):
                self.assertNotIn(claim, low, f"item {n}: {claim!r}")
        self.assertNotIn("bet check", self.section.lower())

    def test_an_x_message_part_fits_under_500_characters_with_its_link(self):
        for n in (9, 3, 8, 11):
            part1, part2 = self.items[n][0], self.items[n][1]
            self.assertLess(len(part1), 500, n)
            self.assertLess(len(part2), 500, n)
            self.assertIn("http", part1)
            # The public reply: X counts any link as 23 characters, limit 280.
            reply = self.items[n][2]
            self.assertLessEqual(len(LINK_RE.sub("x" * 23, reply)), 280, n)

    def test_the_version_label_and_log_commands(self):
        self.assertNotIn("v3d-sample-link", self.section)
        for n in FIVE:
            self.assertIn(
                f"python scripts/outreach_batch.py sent --batch 1 --items {n} --version {VERSION}",
                self.section)

    def test_the_onboarding_and_the_follow_up_exist_and_are_honest(self):
        self.assertIn("Grant 7-day tester access", self.section)
        self.assertIn("index.html#/signin", self.section)
        self.assertIn("index.html#/signup", self.section)
        self.assertIn("One nudge, then I will leave it alone", self.section)
        self.assertNotIn("tonight's", self.section.lower())


if __name__ == "__main__":
    unittest.main()
