"""The two sign-in walls have a dog and a short line, and the member app's labels are sentences (round 2, 2026-10-19).

The critic: "Member app + admin: sign-in walls: add the dog rig + a short headline to both sign-in screens; remove script-forced uppercase
on the member tab bar/labels (CSS text-transform none; change hardcoded uppercase strings to sentence case where they're presentation)."
The admin page keeps exactly ONE script (tests/test_admin_dashboard.py), so its dog is a snapshot of the rig written into the markup.
Small labels in tables, chips and tags stay in capitals by CSS; what is not allowed is a label that is capitals in the source.
"""

# Copy updated per owner ruling 2026-10-20, complete-product positioning (no beta / early-access / paused hedging; invite wording).
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
read = lambda rel: (WEB / rel).read_text(encoding="utf-8")  # noqa: E731


class TheAdminSignInWall(unittest.TestCase):
    HTML = read("admin.html")
    CARD = re.search(r'<form class="adm-gate__card".*?</form>', HTML, re.S).group(0)

    def test_the_card_opens_on_a_dog_and_a_short_line(self):
        self.assertRegex(self.CARD, r'<div class="adm-gate__dog" data-hook="admin-gate-dog" aria-hidden="true"><svg class="dk-badge"')
        self.assertIn('data-pose="thinking"', self.CARD)
        self.assertIn('data-breed="poodle"', self.CARD, "Professor Paws, the house model's own dog")
        self.assertIn('<p class="adm-gate__kicker">Back office</p>', self.CARD)
        self.assertLess(self.CARD.index("adm-gate__dog"), self.CARD.index("adm-gate__title"))

    def test_the_dog_is_decorative_and_the_rest_of_the_card_is_unchanged(self):
        self.assertIn("aria-hidden", self.CARD.split("<svg", 1)[0] + self.CARD.split("<svg", 1)[1][:400])
        for needle in ('<h1 class="adm-gate__title">Admin sign-in</h1>', 'type="password"', 'data-hook="admin-token-input"', 'data-hook="admin-gate-submit"'):
            self.assertIn(needle, self.CARD)
        self.assertEqual(len(re.findall(r"<script\b", self.HTML)), 1, "the admin page keeps exactly one script")

    def test_the_snapshot_draws_only_hex_colours_and_its_own_defs(self):
        svg = self.CARD[self.CARD.index("<svg"):self.CARD.index("</svg>")]
        for attr in re.findall(r'(?:fill|stroke|stop-color)="([^"]+)"', svg):
            self.assertRegex(attr, r"^(#[0-9a-fA-F]{6}|none|currentColor|rgba\([\d., ]+\)|url\(#lh-[a-z-]+\))$")
        self.assertIn('data-style="mascot"', svg)
        self.assertIn('<defs>', svg, "no script on this page, so the snapshot carries the defs it uses")
        for ref in set(re.findall(r'url\(#([\w-]+)\)', svg)):
            self.assertIn(f'id="{ref}"', svg, f"{ref} is defined inside the snapshot")
        self.assertNotIn("<script", svg)
        self.assertNotRegex(svg, r"\son[a-z]+=")

    def test_the_css_sizes_and_lays_the_dog_out(self):
        css = read("css/lh-app.css")
        self.assertRegex(css, r"\.adm-gate__dog svg \{ width: 88px; height: 88px; \}")
        self.assertIn(".adm-gate__kicker", css)


class TheMemberSignInWall(unittest.TestCase):
    def test_the_gate_dog_is_bigger_and_still_thinking(self):
        js = read("js/lh-gate-dog.js")
        self.assertIn('mood: "thinking"', js)
        self.assertIn("size: 88", js)
        self.assertRegex(read("css/lh-app.css"), r"body\.member-app \.gate__dog svg \{ width: 88px; height: 88px; \}")

    def test_the_gate_eyebrows_are_sentences_in_the_source_and_not_shouted_by_css(self):
        dom = read("js/dom.js")
        for text in ("Invited access ended", "Sign in required", "Subscription ended", "Request failed"):
            self.assertIn(f'class: "gate__eyebrow", text: "{text}"', dom)
        self.assertNotRegex(dom, r'gate__eyebrow", text: "[A-Z ]{6,}"')
        self.assertRegex(read("css/lh-app.css"), r"body\.member-app \.gate__eyebrow \{ text-transform: none;")


class TheMemberLabelsAreSentences(unittest.TestCase):
    LABEL = re.compile(r'label: "([^"]+)"')

    def labels(self, rel):
        return self.LABEL.findall(read(rel))

    def test_no_tab_label_is_capitals_in_the_source_apart_from_the_league_names(self):
        leagues = {"MLB", "NFL", "UFC", "NBA", "NHL"}
        for rel in ("js/main.js", "js/sport.js"):
            shouted = [x for x in self.labels(rel) if x.isupper() and len(x) > 1 and x not in leagues]
            self.assertEqual(shouted, [], f"{rel}: labels that are capitals in the source")

    def test_the_tab_bar_and_rail_say_gameday_matchups_props_playoffs_results(self):
        got = self.labels("js/main.js")
        for word in ("Gameday", "Matchups", "Props", "Playoffs", "Results", "Bets"):
            self.assertIn(word, got)

    def test_the_rail_and_tab_bar_css_does_not_uppercase_them(self):
        member = read("css/member.css")
        self.assertRegex(member, r"body\.member-app \.rail__item-label \{[^}]*text-transform: none")
        self.assertRegex(member, r"body\.member-app \.tabbar__item-label \{[^}]*text-transform: none")
        self.assertRegex(read("css/lh-app.css"), r"body\.member-app \.tabbar__item-label, body\.member-app \.rail__item-label[^{]*\{ text-transform: none;")

    def test_the_shell_status_and_state_cards_are_sentence_case_in_the_source(self):
        shell = read("js/shell.js")
        for text in ("Board updated", "No board yet", "Last updated"):
            self.assertIn(text, shell)
        for text in ("BOARD UPDATED", "NO BOARD YET", "LAST UPDATED"):
            self.assertNotIn(f'"{text}"', shell)
        states = read("js/states.js")
        for text in ('eyebrow = "Loading"', 'eyebrow = "Nothing scheduled"', 'eyebrow = "Capture unreachable"', "Something broke on our side"):
            self.assertIn(text, states)
        today = read("js/today.js")
        for text in ("Check a bet of your own", "Open the full board", "Saved bets"):
            self.assertIn(f'text: "{text}"', today)


if __name__ == "__main__":
    unittest.main()
