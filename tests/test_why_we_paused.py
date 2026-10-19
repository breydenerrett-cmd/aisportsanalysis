"""The public page web/why-we-paused.html (visible title "Why we stopped publishing MLB picks"), the posts that point at it,
and the one link to it on the landing page.

THE PAGE is static copy for a reader who bets but does not code. It is the owner's honest account of why MLB
picks were paused (docs/decisions/MLB_VALUE_PICKS_PAUSED.md, docs/research/loss_diagnosis/00_SYNTHESIS.md),
so this file pins what it must say (the result, the three findings, the bug, the luck, the plan and the
"not claiming" list), what it must never say (a profit, edge or win-rate claim, Bet Check, a guarantee),
that it is served like web/sample.html, that web/js/why-paused.js stays a tiny tracker, and that the drafts
in docs/sales/POSTS_2026-10-17.md respect the same rules and X's 280-character limit.
No network. Serving is checked through api/web.py's own route functions (skipped without FastAPI).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "web" / "why-we-paused.html"
SCRIPT = ROOT / "web" / "js" / "why-paused.js"
LANDING = ROOT / "web" / "landing.html"
POSTS = ROOT / "docs" / "sales" / "POSTS_2026-10-17.md"
URL = "https://linehound.app/web/why-we-paused.html"

MARKUP = PAGE.read_text(encoding="utf-8")


def _visible(html: str) -> str:
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


ARTICLE = _visible(MARKUP.split("<article", 1)[1].split("</article>", 1)[0])


def visible_text() -> str:
    return _visible(MARKUP)
BANNED = ("bet check", "betcheck", "guarantee", "profit", "win rate", "win-rate", "sharp", "winning",
          "lock of", "free money")


class ThePageIsServed(unittest.TestCase):

    def test_the_files_exist_and_the_title_is_the_agreed_one(self):
        self.assertTrue(PAGE.is_file() and SCRIPT.is_file())
        # owner voice pass, 2026-10-18: the visible title is "Why we stopped publishing MLB picks"; the file name and URL stay
        self.assertIn("<title>Why we stopped publishing MLB picks", MARKUP)
        self.assertIn('<h1 data-hook="why-paused-title">Why we stopped publishing MLB picks</h1>', MARKUP)
        self.assertNotIn("paused our picks", visible_text())
        self.assertIn(f'<link rel="canonical" href="{URL}">', MARKUP)

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI not installed")
    def test_it_is_served_the_way_sample_html_is(self):
        from api import web
        for name in ("why-we-paused.html", "js/why-paused.js"):
            self.assertEqual(web._safe_path(name), (web.WEB_DIR / name).resolve(), name)
        page = web.get_web_asset("why-we-paused.html")
        sample = web.get_web_asset("sample.html")
        self.assertEqual(Path(page.path), PAGE.resolve())
        self.assertEqual(page.headers.get("cache-control"), sample.headers.get("cache-control"))
        # the container copies the whole web/ directory, so nothing else needs admitting
        self.assertIn("COPY web/ web/", (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8"))

    def test_it_uses_the_same_shell_and_styles_as_the_sample_page(self):
        sample = (ROOT / "web" / "sample.html").read_text(encoding="utf-8")
        sheets = lambda html: re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
        self.assertEqual(sheets(MARKUP), sheets(sample))
        for hook in ('data-hook="app-outlet"', 'data-hook="disclaimer-host"', 'class="lh-nav"'):
            self.assertIn(hook, MARKUP)
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1', MARKUP)
        # two module scripts, the tracker and the shared navigation; no inline script
        self.assertEqual(re.findall(r"<script\b[^>]*>", MARKUP),
                         ['<script type="module" src="js/why-paused.js">', '<script type="module" src="js/nav.js">'])

    def test_the_script_only_tracks_and_mounts_the_footer(self):
        js = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('WHY_PAUSED_PAGE = "why-paused"', js)
        self.assertIn("trackPublicPageView(WHY_PAUSED_PAGE)", js)
        self.assertIn("renderDisclaimerFooter", js)
        self.assertNotIn("apiGet", js)
        self.assertNotIn("fetch(", js)
        from_funnel = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")  # api/funnel.py PAGE_LABEL_RE
        self.assertRegex("why-paused", from_funnel)


class TheCopyIsTheAgreedAccount(unittest.TestCase):

    def test_the_length_is_a_page_not_a_pamphlet(self):
        words = len(ARTICLE.split())
        self.assertTrue(500 <= words <= 700, words)

    def test_the_key_sentences(self):
        for sentence in (
            "Since September 22 we put out 178 graded bets: mostly player props, some moneylines.",
            "The 178 bets went 97-81 and finished 1.4 units down.",
            "We paid extra on every bet, by design.",
            "Our forecasts had nothing the market didn't.",
            "Our ranking picked our worst mistakes.",
            "At the market's own numbers, bets like ours were expected to lose about 7.6 units. We lost 1.4.",
            "Picks come back only if a test we set up in advance shows that we beat the closing price.",
        ):
            self.assertIn(sentence, ARTICLE, sentence)

    def test_every_section_is_there_in_order(self):
        order = ["What we put out", "How it went", "What we found when we took it apart",
                 "The bug", "Where we got lucky", "What happens now", "What we're not saying"]
        heads = re.findall(r"<h2>(.*?)</h2>", MARKUP)
        self.assertEqual(heads, order)

    def test_the_headline_figures_are_shown_beside_the_better_looking_one(self):
        # Losers at the same size as winners: the narrower, worse headline numbers are on the page too.
        for figure in ("16-17", "down 5.05 units", "27-33", "down 9.22 units", "17 withdrawn picks"):
            self.assertIn(figure, ARTICLE, figure)

    def test_the_numbers_are_the_synthesis_numbers(self):
        for figure in ("178", "97-81", "1.4 units", "about 2.4 points", "6,818", "7.6 units", "82 bets", "1.7 points"):
            self.assertIn(figure, ARTICLE, figure)

    def test_what_it_does_not_claim_is_a_list_of_four_denials(self):
        block = re.search(r'data-hook="why-paused-not-claiming">(.*?)</ul>', MARKUP, re.S).group(1)
        self.assertEqual(len(re.findall(r"<li>", block)), 4)
        text = _visible(block)
        self.assertIn("analysis, not advice", text)
        self.assertIn("a small sample", text)

    def test_links_to_the_record_the_sample_and_the_synthesis(self):
        links = re.search(r'data-hook="why-paused-links">(.*?)</ul>', MARKUP, re.S).group(1)
        self.assertIn('href="index.html#/record-card"', links)
        self.assertIn('href="sample.html"', links)
        self.assertIn("/docs/research/loss_diagnosis/00_SYNTHESIS.md", links)
        self.assertTrue((ROOT / "docs" / "research" / "loss_diagnosis" / "00_SYNTHESIS.md").is_file())
        self.assertTrue((ROOT / "web" / "sample.html").is_file())

    def test_no_banned_word_and_no_edge_claim(self):
        text = (ARTICLE + " " + re.search(r'name="description" content="([^"]*)"', MARKUP).group(1)).lower()
        for word in BANNED:
            self.assertNotIn(word, text, word)
        # "edge" appears nowhere: neither as a claim nor as a denial
        self.assertNotRegex(text, r"\bedge\b")
        self.assertNotRegex(text, r"\bev\b|expected value|\bclv\b|\broi\b|\byield\b")


class TheLandingPageLinksToIt(unittest.TestCase):

    def test_one_short_human_line_on_the_kennel_screen_links_to_it(self):
        # owner voice pass, 2026-10-18: the honesty essays on the landing page are one human line and this link
        landing = re.sub(r"<!--.*?-->", "", LANDING.read_text(encoding="utf-8"), flags=re.S)
        line = re.search(r'<p class="lbhero__straight" data-hook="kennel-straight">(.*?)</p>', landing, re.S).group(1)
        self.assertEqual(landing.count('data-hook="hero-why-paused-link"'), 1)
        self.assertIn('href="why-we-paused.html"', line)
        self.assertIn("Why we stopped publishing MLB picks", line)
        self.assertLess(len(_visible(line)), 220, "one line, not an essay")
        self.assertEqual(landing.count("why-we-paused.html"), 1)
        # it sits inside the first screen, before the AI desk section
        self.assertLess(landing.index("kennel-straight"), landing.index('data-hook="hero"'))


class ThePostsRespectTheSameRules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = POSTS.read_text(encoding="utf-8")
        parts = re.split(r"\n## \d\. ", cls.text)
        cls.thread, cls.discord, cls.reply = (re.findall(r"```\n(.*?)\n```", p, re.S) for p in parts[1:4])

    def test_the_x_thread_is_six_to_eight_posts_each_under_280_characters(self):
        self.assertTrue(6 <= len(self.thread) <= 8, len(self.thread))
        for i, post in enumerate(self.thread, 1):
            self.assertLess(len(post), 280, f"post {i}: {len(post)} characters")
            self.assertTrue(post.startswith(f"{i}/ "), post[:10])

    def test_the_first_post_stands_alone_and_the_link_is_in_the_last(self):
        first = self.thread[0]
        self.assertNotIn("http", first)
        self.assertIn("97-81", first)
        self.assertIn("still a loss", first)
        last = self.thread[-1]
        self.assertIn(f"{URL}?utm_source=x&utm_medium=post&utm_campaign=why_paused", last)

    def test_the_discord_post_is_under_1200_characters_and_tagged(self):
        self.assertEqual(len(self.discord), 1)
        post = self.discord[0]
        self.assertLess(len(post), 1200, len(post))
        self.assertIn(f"{URL}?utm_source=discord&utm_medium=post&utm_campaign=why_paused", post)
        self.assertIn("Analysis, not advice", post)

    def test_the_reply_is_one_paragraph_with_a_tagged_link(self):
        self.assertEqual(len(self.reply), 1)
        reply = self.reply[0]
        self.assertNotIn("\n", reply)
        self.assertIn(f"{URL}?utm_source=x&utm_medium=post&utm_campaign=why_paused", reply)
        self.assertIn("Analysis, not advice", reply)

    def test_no_banned_word_anywhere_in_the_drafts(self):
        low = " ".join(self.thread + self.discord + self.reply).lower()
        for word in BANNED:
            self.assertNotIn(word, low, word)
        self.assertNotRegex(low, r"\bedge\b")

    def test_the_figures_are_the_ones_on_the_page(self):
        low = " ".join(self.thread + self.discord + self.reply)
        for figure in ("178", "97-81", "1.4 units", "7.6"):
            self.assertIn(figure, low, figure)
        # the file warns the owner that the record page's headline is narrower and worse
        self.assertIn("16-17", self.text)
        self.assertIn("27-33", self.text)


if __name__ == "__main__":
    unittest.main()
