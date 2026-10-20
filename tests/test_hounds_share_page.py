"""The shared-dog page (src/hounds/share_page.py): the owner's title and description formats, everything
escaped, and a 404 page for an id that is not a dog. Pure functions: no FastAPI, no network.
"""

from __future__ import annotations

import re
import unittest

from src.hounds import share_page as sp

INFO = {"id": "steamy_setter", "name": "Steamy Setter", "tagline": "Follows the steam.",
        "catchphrase": "Follow the money. Ask questions never.",
        "record": {"bets": 109, "wins": 63, "losses": 46, "pushes": 0, "units_average_price": 4.2,
                   "units_recorded_price": 5.1}}


def meta(page, prop):
    m = re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)"', page)
    return m.group(1) if m else None


class TheDescriptionIsTheOwnersFormat(unittest.TestCase):
    def test_title_and_description(self):
        page = sp.render_dog("steamy_setter", INFO, base="https://linehound.app")
        self.assertIn("<title>Steamy Setter | LineHound Kennel</title>", page)
        self.assertEqual(meta(page, "og:title"), "Steamy Setter | LineHound Kennel")
        self.assertEqual(meta(page, "og:description"), "63-46 · +4.20u paper · Follow the money. Ask questions never.")
        self.assertEqual(meta(page, "twitter:description"), meta(page, "og:description"))
        self.assertEqual(meta(page, "og:url"), "https://linehound.app/d/steamy_setter")
        self.assertEqual(meta(page, "twitter:card"), "summary_large_image")   # the card image (share_card.py) makes it a large one

    def test_units_use_the_average_price_else_the_recorded_price(self):
        rec = dict(INFO["record"], units_average_price=None)
        self.assertEqual(sp.units_text(rec), "+5.10")
        self.assertEqual(sp.units_text(dict(INFO["record"], units_average_price=-1.005, bets=5)), "-1.00")
        self.assertEqual(sp.units_text({"bets": 3, "units_average_price": 0.0}), "0.00")
        self.assertEqual(sp.units_text({"bets": 0}), "no bets yet")

    def test_a_dog_with_no_bets_and_no_catchphrase_still_makes_a_sentence(self):
        page = sp.render_dog("rookie", {"id": "rookie", "name": "Rookie", "record": {"bets": 0}, "tagline": "New here."})
        self.assertEqual(meta(page, "og:description"), "0-0 · no bets yet · New here.")

    def test_pushes_show_in_the_record_like_the_page(self):
        self.assertEqual(sp.wl_text({"bets": 10, "wins": 5, "losses": 4, "pushes": 1}), "5-4-1")

    def test_it_sends_a_person_on_to_the_real_page_with_a_refresh_and_a_link(self):
        page = sp.render_dog("steamy_setter", INFO)
        self.assertIn('<meta http-equiv="refresh" content="0; url=/web/hound.html?id=steamy_setter">', page)
        self.assertIn('<a href="/web/hound.html?id=steamy_setter">Open Steamy Setter on LINEHOUND</a>', page)

    def test_the_hard_lines_are_on_the_page(self):
        page = sp.render_dog("steamy_setter", INFO)
        for line in ("Paper bets only, not advice.", "21+", "Gamble responsibly", "1-800-GAMBLER"):
            self.assertIn(line, page)
        self.assertNotRegex(page, r"(?i)\block\b|guarantee|can'?t lose|sure thing|\bedge\b|profit")


class EverythingIsEscaped(unittest.TestCase):
    HOSTILE = '"><script>alert(1)</script><img src=x onerror=alert(2)> & \' </title>'

    def test_a_builders_hostile_name_and_tagline_never_reach_the_page_as_markup(self):
        info = {"id": "u-abc", "name": self.HOSTILE, "tagline": self.HOSTILE, "catchphrase": self.HOSTILE,
                "record": {"bets": 1, "wins": 1, "losses": 0}}
        page = sp.render_dog("u-abc", info)
        self.assertNotIn("<script", page)
        self.assertNotIn("<img", page)
        self.assertNotIn("onerror=alert(2)>", page)
        self.assertEqual(page.count("</title>"), 1)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&quot;", page)
        # attribute values stay inside their quotes: every content="..." has no raw quote inside
        for m in re.finditer(r'content="([^"]*)"', page):
            self.assertNotIn("<", m.group(1))

    def test_an_id_in_a_url_is_percent_encoded_and_escaped(self):
        page = sp.render_dog('a"b', {"id": 'a"b', "name": "X", "record": {}})
        self.assertNotIn('id=a"b', page)
        self.assertIn("a%22b", page)

    def test_only_plain_ids_are_looked_up(self):
        for bad in ("<script>", "a b", "a/b", "", "x" * 81, "a;b", "a\nb", '"'):
            self.assertEqual(sp.lookup(bad), (sp.STATE_UNKNOWN, None), repr(bad))

    def test_the_origin_can_be_set_for_a_staging_host(self):
        import os
        old = os.environ.get(sp.ORIGIN_ENV)
        os.environ[sp.ORIGIN_ENV] = "https://staging.example/"
        try:
            self.assertEqual(sp.origin(), "https://staging.example")
            self.assertIn("https://staging.example/d/steamy_setter", sp.render_dog("steamy_setter", INFO, base=None))
        finally:
            if old is None:
                os.environ.pop(sp.ORIGIN_ENV, None)
            else:
                os.environ[sp.ORIGIN_ENV] = old


class NotFoundAndWarming(unittest.TestCase):
    def test_the_404_page_names_no_dog_and_links_to_the_kennel(self):
        page = sp.render_not_found('<b>"x"</b>')
        self.assertIn("No dog by that name", page)
        self.assertNotIn("<b>", page)
        self.assertIn("/web/hounds.html", page)
        self.assertIn("1-800-GAMBLER", page)

    def test_the_warming_page_says_to_try_again(self):
        self.assertIn("Try this link again in a minute", sp.render_warming())


if __name__ == "__main__":
    unittest.main()
