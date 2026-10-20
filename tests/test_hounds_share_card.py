"""The shared-dog picture: what it says (src/hounds/share_card.py), how it is drawn (share_render.py), the meta tags
that point at it (share_page.py), the route that serves it (api/hounds_share.py) and the quiz story image (web/js/share-card.js).

Layers, so each runs where its dependencies are:
  * the spec, the hash, the scrubbing, the tag text: standard library only, run everywhere (Linux CI has no FastAPI, no Pillow);
  * the PNG itself: needs Pillow (skipped without it);
  * the route: needs FastAPI and Pillow (skipped without them);
  * the story image: needs node (skipped without it).
"""

from __future__ import annotations

import io
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from src.hounds import share_card as sc
from src.hounds import share_page as sp

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:                      # Linux CI runs without api/requirements.txt
    HAS_PIL = False
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from tests.hounds_web_runner import HAS_NODE, run_js

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web" / "js"

PUBLIC = {
    "id": "steamy_setter", "name": "Steamy Setter", "tagline": "Follows the steam.",
    "catchphrase": "Follow the money. Ask questions never.", "kind": "house", "status": "running",
    "sports": ["mlb", "nfl"], "settled": 109,
    "record": {"bets": 109, "wins": 63, "losses": 46, "pushes": 0, "units_average_price": 4.2},
    "bankroll": {"start": 1000.0, "current": 1042.4},
    "look": {"coat": "golden", "eyes": "amber", "bg": "teal", "head": "cap", "face": "sunglasses", "neck": "chain",
             "body": "jersey", "number": 23, "style": "elite", "breed": "setter"},
}


def info(**over):
    out = json.loads(json.dumps(PUBLIC))
    out.update(over)
    return out


def meta(page, prop):
    m = re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)"', page)
    return m.group(1) if m else None


class ThePriceTest(unittest.TestCase):
    def test_it_catches_american_prices_and_only_those(self):
        for text in ("Takes the Yankees -110", "+150 dogs", "ml -1500", "−200 favourites", "dogs -110"):
            self.assertTrue(sc.has_price(text), text)
        for text in ("21+ · Paper bets · 1-800-GAMBLER", "63-46", "104-103", "$1,042", "start $1,000", "1-800-426-2537",
                     "Ranked in full at 10 settled bets", "3-2 run", "+4.20"):
            self.assertFalse(sc.has_price(text), text)

    def test_scrub_removes_prices_controls_and_anything_past_latin_1(self):
        self.assertEqual(sc.scrub("Fades -110 chalk"), "Fades chalk")
        self.assertEqual(sc.scrub("  a\tb\u0000c \n d "), "a b c d")
        self.assertEqual(sc.scrub("Rex \U0001F436 the ★ hound"), "Rex the hound")
        self.assertEqual(sc.scrub("x" * 500, 20), "x" * 20)
        self.assertEqual(sc.scrub(None), "")


class TheSpec(unittest.TestCase):
    def test_a_public_dog_says_its_name_kennel_line_sports_record_and_bankroll(self):
        spec = sc.spec_from_info("steamy_setter", info())
        self.assertEqual((spec.name, spec.kennel, spec.record, spec.bankroll, spec.start),
                         ("Steamy Setter", "LINEHOUND house kennel", "63-46", "$1,042", "$1,000"))
        self.assertEqual(spec.tagline, "Follow the money. Ask questions never.")
        self.assertEqual(spec.sports, ("MLB", "NFL"))
        self.assertFalse(spec.generic)
        self.assertIsNone(spec.ranked_note)
        self.assertEqual(spec.breed, "setter")

    def test_a_member_dog_shows_its_kennel_name(self):
        spec = sc.spec_from_info("u-1", info(kind="user", owner_display="Quiet Thunder Kennel"))
        self.assertEqual(spec.kennel, "Quiet Thunder Kennel")

    def test_pushes_show_in_the_record(self):
        spec = sc.spec_from_info("x", info(record={"bets": 10, "wins": 5, "losses": 4, "pushes": 1}, settled=10))
        self.assertEqual(spec.record, "5-4-1")

    def test_a_loss_is_drawn_the_same_way_as_a_win(self):
        win = sc.spec_from_info("x", info(bankroll={"start": 1000, "current": 1180}))
        loss = sc.spec_from_info("x", info(bankroll={"start": 1000, "current": 820}))
        self.assertEqual((win.bankroll, loss.bankroll), ("$1,180", "$820"))
        self.assertEqual([t for t in win.texts() if t not in ("$1,180",)], [t for t in loss.texts() if t not in ("$820",)])

    def test_below_the_ranking_bar_the_card_says_when_the_dog_is_ranked_in_full(self):
        spec = sc.spec_from_info("x", info(settled=3, record={"bets": 3, "wins": 1, "losses": 2, "pushes": 0}))
        self.assertEqual(spec.ranked_note, f"Ranked in full at {sc.MIN_RANKED_BETS} settled bets")
        self.assertIsNone(sc.spec_from_info("x", info(settled=sc.MIN_RANKED_BETS)).ranked_note)

    def test_a_dog_with_no_bets_starts_at_the_start(self):
        spec = sc.spec_from_info("x", info(record={"bets": 0}, settled=0, bankroll=None))
        self.assertEqual((spec.record, spec.bankroll), ("0-0", "$1,000"))

    def test_a_dog_with_bets_and_no_bankroll_block_shows_no_bankroll_never_a_guess(self):
        spec = sc.spec_from_info("x", info(bankroll=None))
        self.assertIsNone(spec.bankroll)

    def test_a_house_dog_with_no_numbers_yet_shows_neither_record_nor_bankroll(self):
        spec = sc.spec_from_info("x", {"name": "Rookie", "record": {}, "catchphrase": "Hello."})
        self.assertEqual((spec.record, spec.bankroll), (None, None))

    def test_the_personality_line_falls_back_to_the_tagline(self):
        self.assertEqual(sc.spec_from_info("x", info(catchphrase="")).tagline, "Follows the steam.")

    def test_a_price_in_the_dogs_own_words_never_reaches_the_card(self):
        spec = sc.spec_from_info("x", info(name="Fade -110", catchphrase="Takes the over at -125", tagline="Dogs +150 only",
                                           owner_display="Kennel +200"))
        for text in spec.texts():
            self.assertFalse(sc.has_price(text), text)
        self.assertEqual(spec.name, "Fade")

    def test_every_string_on_every_card_is_free_of_prices(self):
        for spec in (sc.spec_from_info("a", PUBLIC), sc.generic_spec(), sc.spec_from_info("b", info(settled=1))):
            for text in spec.texts():
                self.assertFalse(sc.has_price(text), text)
            self.assertIn(sc.FOOTER, spec.texts())
        self.assertEqual(sc.FOOTER, "21+ · Paper bets · 1-800-GAMBLER")

    def test_no_claim_words_anywhere_on_a_card(self):
        banned = re.compile(r"(?i)\block\b|guarantee|can'?t lose|sure thing|free money|\bedge\b|\bprofit|\bbeta\b|bet check|\bwinning\b")
        for spec in (sc.spec_from_info("a", PUBLIC), sc.generic_spec()):
            self.assertIsNone(banned.search(" ".join(spec.texts())), spec.texts())
        source = (ROOT / "src" / "hounds" / "share_card.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(?i)bet check", source))


class PublicDogsOnly(unittest.TestCase):
    def test_a_retired_dog_gets_the_generic_card(self):
        spec = sc.spec_from_info("old_dog", info(status="retired"))
        self.assertTrue(spec.generic)
        self.assertEqual(spec.reason, sc.REASON_RETIRED)
        self.assertEqual(spec.digest(), sc.generic_spec().digest())
        self.assertNotIn("Steamy Setter", " ".join(spec.texts()))

    def test_a_retired_block_also_counts(self):
        self.assertTrue(sc.spec_from_info("x", info(status="running", retired={"date": "2026-10-01", "cause": "x"})).generic)

    def test_an_unknown_or_missing_dog_gets_the_generic_card(self):
        for value in (None, [], "dog"):
            self.assertTrue(sc.spec_from_info("x", value).generic)

    def test_the_generic_card_carries_no_record_no_bankroll_and_no_dog_name(self):
        g = sc.generic_spec()
        self.assertEqual((g.record, g.bankroll, g.sports), (None, None, ()))
        self.assertNotIn("RECORD", g.texts())

    def test_spec_for_answers_generic_for_a_dog_the_lookup_does_not_know(self):
        with mock.patch.object(sp, "lookup", lambda hid: (sp.STATE_UNKNOWN, None)):
            self.assertEqual(sc.spec_for("nobody").reason, sc.REASON_UNKNOWN)
        with mock.patch.object(sp, "lookup", lambda hid: (sp.STATE_WARMING, None)):
            self.assertEqual(sc.spec_for("nobody").reason, sc.REASON_WARMING)
        with mock.patch.object(sp, "lookup", mock.Mock(side_effect=RuntimeError("boom"))):
            self.assertTrue(sc.spec_for("nobody").generic)

    def test_spec_for_a_public_dog_goes_through_the_same_lookup_the_page_uses(self):
        with mock.patch.object(sp, "lookup", lambda hid: (sp.STATE_OK, info())):
            self.assertEqual(sc.spec_for("steamy_setter").name, "Steamy Setter")


class TheHash(unittest.TestCase):
    def test_it_is_stable_and_16_hex(self):
        a = sc.spec_from_info("x", info()).digest()
        self.assertRegex(a, r"^[0-9a-f]{16}$")
        self.assertEqual(a, sc.spec_from_info("x", info()).digest())

    def test_anything_the_picture_says_changes_it(self):
        base = sc.spec_from_info("x", info()).digest()
        variants = [info(record={"bets": 110, "wins": 64, "losses": 46, "pushes": 0}), info(bankroll={"start": 1000, "current": 1051}),
                    info(name="Other"), info(catchphrase="Different."), info(sports=["mlb"]), info(owner_display="K"),
                    info(look=dict(PUBLIC["look"], coat="black")), info(settled=2)]
        digests = {sc.spec_from_info("x", v).digest() for v in variants}
        self.assertNotIn(base, digests)
        self.assertEqual(len(digests), len(variants))

    def test_what_the_picture_does_not_say_does_not_change_it(self):
        self.assertEqual(sc.spec_from_info("x", info()).digest(), sc.spec_from_info("x", info(tagline="other", kind="house")).digest())


class TheLookAndBreed(unittest.TestCase):
    def test_the_colour_tables_are_the_pages(self):
        text = (JS / "dog-look.js").read_text(encoding="utf-8")
        for table, ours in (("COATS", {k: tuple(v) for k, v in sc.COATS.items()}), ("EYES", sc.EYES), ("BACKGROUNDS", sc.BACKGROUNDS)):
            block = re.search(rf"export const {table} = \{{(.*?)\n\}};", text, re.S).group(1)
            if table == "COATS":
                theirs = {m.group(1): (m.group(2), m.group(3), m.group(4)) for m in re.finditer(
                    r'(\w+): \{ base: "(#\w+)", shade: "(#\w+)", light: "(#\w+)" \}', block)}
            elif table == "EYES":
                theirs = dict(re.findall(r'(\w+): "(#\w+)"', block))
            else:
                theirs = {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(r'(\w+): \["(#\w+)", "(#\w+)"\]', block)}
            self.assertEqual({k: tuple(v) if isinstance(v, (list, tuple)) else v for k, v in ours.items()}, theirs, table)

    def test_the_breed_words_are_the_rigs(self):
        text = (JS / "dog-rig.js").read_text(encoding="utf-8")
        block = re.search(r"export const NAME_BREED = \{(.*?)\n\};", text, re.S).group(1)
        self.assertEqual(sc.NAME_BREED, dict(re.findall(r'(\w+): "(\w+)"', block)))
        vibes = re.search(r"export const VIBE_BREED = \{(.*?)\};", text, re.S).group(1)
        self.assertEqual(sc.VIBE_BREED, dict(re.findall(r'(\w+): "(\w+)"', vibes)))

    def test_the_hash_is_the_pages(self):
        # FNV-1a of "retriever" computed by web/js/dog-look.js hashStr (checked once under node and pinned here)
        self.assertEqual(sc.hash_str(""), 2166136261)
        self.assertEqual(sc.hash_str("a"), 0xE40C292C)

    def test_a_dog_nobody_dressed_gets_the_pages_default_look(self):
        look = sc.default_look("steamy_setter")
        self.assertIn(look["coat"], sc.COATS)
        self.assertEqual(look, sc.default_look("steamy_setter"))
        self.assertEqual(look["head"], "none")

    def test_clean_look_refuses_anything_off_the_whitelist(self):
        look = sc.clean_look({"coat": "<script>", "eyes": "blue", "head": "crown", "body": "none", "number": 5, "style": 7})
        self.assertEqual((look["coat"], look["eyes"], look["head"], look["style"], look["number"]), ("tan", "blue", "none", "mascot", None))

    def test_breed_choice_order(self):
        self.assertEqual(sc.breed_for({"breed": "husky"}, "x", "Chalk Chihuahua"), "husky")
        self.assertEqual(sc.breed_for({"breed": "auto"}, "x", "Chalk Chihuahua"), "chihuahua")
        self.assertEqual(sc.breed_for({}, "x", "Plain Name", "degen"), "husky")
        self.assertIn(sc.breed_for({}, "x", "Plain Name"), sc.LEGACY_BREEDS)


@unittest.skipUnless(HAS_PIL, "Pillow not installed")
class ThePng(unittest.TestCase):
    def setUp(self):
        sc.clear_cache()

    def png(self, spec):
        return Image.open(io.BytesIO(sc.png_for(spec)))

    def test_the_card_is_1200_by_630(self):
        im = self.png(sc.spec_from_info("steamy_setter", PUBLIC))
        self.assertEqual((im.format, im.size), ("PNG", (1200, 630)))

    def test_the_generic_card_is_the_same_size(self):
        self.assertEqual(self.png(sc.generic_spec()).size, (1200, 630))

    def test_a_retired_dog_is_byte_for_byte_the_generic_card(self):
        self.assertEqual(sc.png_for(sc.spec_from_info("old", info(status="retired"))), sc.png_for(sc.generic_spec()))

    def test_a_public_dog_is_not_the_generic_card(self):
        self.assertNotEqual(sc.png_for(sc.spec_from_info("a", PUBLIC)), sc.png_for(sc.generic_spec()))

    def test_it_draws_exactly_the_words_in_the_spec_and_no_price(self):
        from PIL import ImageDraw
        drawn = []
        real = ImageDraw.ImageDraw.text

        def spy(self, xy, text, *a, **k):
            drawn.append(str(text))
            return real(self, xy, text, *a, **k)

        for spec in (sc.spec_from_info("a", PUBLIC), sc.spec_from_info("b", info(settled=2, record={"bets": 2, "wins": 1, "losses": 1})),
                     sc.generic_spec()):
            drawn.clear()
            with mock.patch.object(ImageDraw.ImageDraw, "text", spy):
                from src.hounds import share_render
                share_render.render_card(spec)
            joined = "".join(drawn)
            for text in drawn:
                self.assertFalse(sc.has_price(text), text)
            self.assertFalse(sc.has_price(" ".join(drawn)))
            for must in (spec.name, spec.record, spec.bankroll, spec.ranked_note):
                if must:
                    self.assertIn(must.replace(" ", ""), joined.replace(" ", "").replace("...", ""))

    def test_every_style_every_accessory_and_every_breed_draws(self):
        for breed in __import__("src.hounds.interact.look", fromlist=["BREEDS"]).BREEDS:
            look = dict(PUBLIC["look"], breed=breed)
            self.assertEqual(self.png(sc.spec_from_info("x" + breed, info(look=look))).size, (1200, 630), breed)
        for style in ("mascot", "street", "elite"):
            for head, neck, body, face in (("cap", "chain", "jersey", "sunglasses"), ("visor", "collar", "hoodie", "none"),
                                           ("headband", "bandana", "none", "none")):
                look = dict(PUBLIC["look"], style=style, head=head, neck=neck, body=body, face=face)
                self.assertEqual(self.png(sc.spec_from_info("s", info(look=look))).size, (1200, 630), (style, head))

    def test_a_very_long_name_and_tagline_still_fit_the_canvas(self):
        spec = sc.spec_from_info("x", info(name="W" * 60, catchphrase="word " * 60, owner_display="K" * 60, sports=["a", "b", "c", "d", "e"]))
        self.assertEqual(self.png(spec).size, (1200, 630))

    def test_the_picture_is_rendered_once_per_hash(self):
        spec = sc.spec_from_info("a", PUBLIC)
        first = sc.png_for(spec)
        with mock.patch("src.hounds.share_render.render_card", side_effect=AssertionError("rendered twice")):
            self.assertIs(sc.png_for(spec), first)

    def test_the_cache_is_bounded(self):
        for i in range(sc.CACHE_ENTRIES + 5):
            sc.png_for(sc.spec_from_info("d", info(name=f"Dog {i}")))
        self.assertLessEqual(len(sc._CACHE), sc.CACHE_ENTRIES)

    def test_the_fonts_ship_beside_the_renderer(self):
        from src.hounds import share_render
        for name in (share_render.DISPLAY_BOLD, share_render.DISPLAY_SEMI, share_render.BODY):
            self.assertGreater((share_render.ASSETS / name).stat().st_size, 10_000, name)


class TheMetaTags(unittest.TestCase):
    def page(self, **over):
        return sp.render_dog("steamy_setter", info(**over), base="https://linehound.app")

    def test_a_dog_link_unfurls_as_a_large_image(self):
        page = self.page()
        digest = sc.spec_from_info("steamy_setter", info()).digest()
        self.assertEqual(meta(page, "twitter:card"), "summary_large_image")
        self.assertEqual(meta(page, "og:image"), f"https://linehound.app/d/steamy_setter/card.png?v={digest}")
        self.assertEqual(meta(page, "twitter:image"), meta(page, "og:image"))
        self.assertEqual((meta(page, "og:image:width"), meta(page, "og:image:height"), meta(page, "og:image:type")),
                         ("1200", "630", "image/png"))
        self.assertEqual(meta(page, "og:title"), "Steamy Setter | LineHound Kennel")
        self.assertEqual(meta(page, "og:description"), "63-46 · +4.20u paper · Follow the money. Ask questions never.")
        self.assertIn("Steamy Setter", meta(page, "og:image:alt"))

    def test_a_changed_record_is_a_new_image_url(self):
        a = meta(self.page(), "og:image")
        b = meta(self.page(record={"bets": 110, "wins": 64, "losses": 46, "pushes": 0}), "og:image")
        self.assertNotEqual(a, b)

    def test_a_retired_dog_points_at_the_generic_card(self):
        page = self.page(status="retired")
        self.assertEqual(meta(page, "og:image"), f"https://linehound.app/d/steamy_setter/card.png?v={sc.generic_spec().digest()}")
        self.assertEqual(meta(page, "og:image:alt"), "A LINEHOUND hound")

    def test_the_other_pages_keep_the_small_card_and_no_image(self):
        for page in (sp.render_not_found("x"), sp.render_warming()):
            self.assertEqual(meta(page, "twitter:card"), "summary")
            self.assertIsNone(meta(page, "og:image"))

    def test_the_image_url_is_escaped_and_the_id_percent_encoded(self):
        page = sp.render_dog('a"b', {"id": 'a"b', "name": 'X"><script>', "record": {}}, base="https://linehound.app")
        self.assertNotIn("<script", page)
        self.assertIn("a%22b/card.png", meta(page, "og:image"))
        for m in re.finditer(r'content="([^"]*)"', page):
            self.assertNotIn("<", m.group(1))

    def test_the_page_still_sends_a_person_on_and_keeps_the_hard_lines(self):
        page = self.page()
        self.assertIn('<meta http-equiv="refresh" content="0; url=/web/hound.html?id=steamy_setter">', page)
        for line in ("Paper bets only, not advice.", "21+", "1-800-GAMBLER"):
            self.assertIn(line, page)

    def test_info_from_summary_carries_what_the_card_reads(self):
        summary = {"id": "u1", "name": "U", "kind": "user", "status": "running", "owner_display": "K", "sports": ["mlb"],
                   "bankroll": {"start": 1000, "current": 990}, "settled": 4, "record": {"bets": 4},
                   "persona": {"catchphrase": "c", "vibe": "nerd"}}
        got = sp.info_from_summary(summary)
        spec = sc.spec_from_info("u1", got)
        self.assertEqual((spec.kennel, spec.sports, spec.bankroll, spec.breed), ("K", ("MLB",), "$990", "schnauzer"))


@unittest.skipUnless(HAS_FASTAPI and HAS_PIL, "fastapi and Pillow not installed")
class TheRoute(unittest.TestCase):
    def setUp(self):
        from api.hounds_share import router
        sc.clear_cache()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def get(self, path, lookup, **kw):
        with mock.patch.object(sp, "lookup", lookup):
            return self.client.get(path, **kw)

    def ok(self, hid):
        return (sp.STATE_OK, info())

    def test_a_public_dog_gets_its_card_with_the_hash_as_etag(self):
        r = self.get("/d/steamy_setter/card.png", self.ok)
        digest = sc.spec_from_info("steamy_setter", info()).digest()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertEqual(r.headers["etag"], f'"{digest}"')
        self.assertEqual(Image.open(io.BytesIO(r.content)).size, (1200, 630))

    def test_cache_control_trusts_a_matching_hash_for_a_day_and_nothing_else_for_five_minutes(self):
        digest = sc.spec_from_info("steamy_setter", info()).digest()
        self.assertEqual(self.get(f"/d/steamy_setter/card.png?v={digest}", self.ok).headers["cache-control"], "public, max-age=86400")
        self.assertEqual(self.get("/d/steamy_setter/card.png?v=stale", self.ok).headers["cache-control"], "public, max-age=300")
        self.assertEqual(self.get("/d/steamy_setter/card.png", self.ok).headers["cache-control"], "public, max-age=300")

    def test_a_matching_etag_is_a_304_with_no_body(self):
        digest = sc.spec_from_info("steamy_setter", info()).digest()
        r = self.get("/d/steamy_setter/card.png", self.ok, headers={"If-None-Match": f'"{digest}"'})
        self.assertEqual((r.status_code, r.content), (304, b""))
        self.assertEqual(r.headers["etag"], f'"{digest}"')

    def test_a_retired_dog_gets_the_generic_card_not_a_404(self):
        r = self.get("/d/old_dog/card.png", lambda hid: (sp.STATE_OK, info(status="retired")))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, sc.png_for(sc.generic_spec()))

    def test_an_unknown_dog_and_a_hostile_id_get_the_generic_card(self):
        generic = sc.png_for(sc.generic_spec())
        self.assertEqual(self.get("/d/nobody/card.png", lambda hid: (sp.STATE_UNKNOWN, None)).content, generic)
        self.assertEqual(self.client.get("/d/%3Cscript%3Ealert(1)%3E/card.png").content, generic)
        # an encoded slash splits the path: nothing matches, and nothing is echoed
        self.assertNotIn(b"script", self.client.get("/d/%3Cscript%3E%2Fx/card.png").content)

    def test_a_kennel_still_warming_gets_the_generic_card_for_thirty_seconds(self):
        r = self.get("/d/steamy_setter/card.png", lambda hid: (sp.STATE_WARMING, None))
        self.assertEqual((r.status_code, r.headers["cache-control"]), (200, "public, max-age=30"))

    def test_without_pillow_the_answer_is_503_not_a_broken_image(self):
        with mock.patch.object(sc, "png_for", side_effect=sc.RenderUnavailable("no PIL")):
            r = self.get("/d/steamy_setter/card.png", self.ok)
        self.assertEqual((r.status_code, r.headers["cache-control"]), (503, "no-store"))

    def test_the_page_route_still_answers_and_names_the_picture(self):
        r = self.get("/d/steamy_setter", self.ok)
        self.assertEqual(r.status_code, 200)
        self.assertIn('content="summary_large_image"', r.text)
        self.assertIn("/d/steamy_setter/card.png?v=", r.text)


STORY_RESULT = {
    "spec": {"name": "Closer"}, "look": None, "breed": "retriever",
    "rule_cards": [{"source": "personality", "label": "Underdog Hunter"}, {"source": "archetype", "label": "Steam Chaser"},
                   {"source": "english", "label": "Your words"}, {"source": "archetype", "label": "Fade the +120 dog"},
                   {"source": "archetype", "label": "Tired Legs"}, {"source": "archetype", "label": "Primetime"},
                   {"source": "archetype", "label": "A fifth card"}],
}
DOT_FOOTER = "21+ · Paper bets · 1-800-GAMBLER"


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStoryImage(unittest.TestCase):
    """web/js/share-card.js: the 1080x1920 quiz-result story and its Share button, under node with a recording canvas."""

    def run_snippet(self, body):
        return run_js('import * as S from "./share-card.js";\nconst RESULT = ' + json.dumps(STORY_RESULT) + ';\n' + body)

    def test_the_story_is_1080_by_1920_with_the_owners_words(self):
        out = self.run_snippet('console.log(JSON.stringify({w: S.STORY_W, h: S.STORY_H, cta: S.STORY_CTA, footer: S.STORY_FOOTER, label: S.SHARE_LABEL}));')
        self.assertEqual(out, {"w": 1080, "h": 1920, "cta": "Find your hound at linehound.app", "footer": DOT_FOOTER, "label": "Share"})

    def test_archetype_and_three_trait_lines_never_a_price_or_a_generic_label(self):
        out = self.run_snippet('console.log(JSON.stringify(S.storyLines(RESULT)));')
        self.assertEqual(out["archetype"], "Underdog Hunter")
        self.assertEqual(out["traits"], ["Steam Chaser", "Tired Legs", "Primetime"])      # not "Your words", not the +120 line, at most three
        for text in [out["archetype"], *out["traits"], out["cta"], out["footer"]]:
            self.assertFalse(sc.has_price(text), text)

    def test_the_js_price_test_agrees_with_the_python_one(self):
        samples = ["Takes the Yankees -110", "+150 dogs", "ml -1500", "dogs -110", DOT_FOOTER, "63-46",
                   "104-103", "$1,042", "1-800-426-2537", "+4.20", "3-2 run"]
        out = self.run_snippet("console.log(JSON.stringify(" + json.dumps(samples) + ".map((t) => S.hasPrice(t))));")
        self.assertEqual(out, [sc.has_price(t) for t in samples])

    def test_drawing_places_every_line_and_the_footer_and_nothing_else(self):
        out = self.run_snippet("""
const calls = [];
const ctx = new Proxy({}, { get: (t, k) => (k === "measureText" ? (s) => ({ width: String(s).length * 20 })
  : k === "createLinearGradient" ? () => ({ addColorStop() {} })
  : (...a) => { calls.push([String(k), a.map(String)]); }), set: () => true });
S.drawStory(ctx, S.storyLines(RESULT), null);
console.log(JSON.stringify(calls.filter((c) => c[0] === "fillText").map((c) => c[1][0])));""")
        self.assertIn("Underdog Hunter", out)
        self.assertIn("Find your hound at linehound.app", out)
        self.assertEqual([t.strip() for t in DOT_FOOTER.split("·")], [t for t in out if t in ("21+", "Paper bets", "1-800-GAMBLER")])
        for trait in ("Steam Chaser", "Tired Legs", "Primetime"):
            self.assertIn(trait, out)
        for text in out:
            self.assertFalse(sc.has_price(text), text)
        self.assertNotIn("Fade the +120 dog", out)

    def share(self, nav_js):
        return self.run_snippet("""
const clicks = [];
const anchor = () => ({ attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, click() { clicks.push(this.attrs.download); } });
const doc = { createElement: anchor, body: { appendChild() {}, removeChild() {} } };
const blob = new Blob(["png"], { type: "image/png" });
""" + nav_js + """
const outcome = await S.shareStory(RESULT, { nav, doc, blob });
console.log(JSON.stringify({ outcome, clicks, shared }));""")

    def test_a_phone_that_can_share_files_shares_the_png(self):
        out = self.share("""
const shared = [];
const nav = { canShare: (d) => !!d.files, share: async (d) => { shared.push({ name: d.files[0].name, type: d.files[0].type, text: d.text }); } };""")
        self.assertEqual(out["outcome"], "shared")
        self.assertEqual(out["shared"], [{"name": "my-linehound.png", "type": "image/png", "text": "Find your hound at linehound.app"}])
        self.assertEqual(out["clicks"], [])

    def test_a_browser_without_file_sharing_downloads_the_png(self):
        for nav in ("const shared = []; const nav = {};", "const shared = []; const nav = { share: async () => {}, canShare: () => false };"):
            out = self.share(nav)
            self.assertEqual((out["outcome"], out["clicks"]), ("downloaded", ["my-linehound.png"]))

    def test_a_cancelled_share_sheet_is_not_an_error_and_does_not_download(self):
        out = self.share("""
const shared = [];
const nav = { canShare: () => true, share: async () => { const e = new Error("x"); e.name = "AbortError"; throw e; } };""")
        self.assertEqual((out["outcome"], out["clicks"]), ("cancelled", []))

    def test_a_share_that_breaks_falls_back_to_the_download(self):
        out = self.share("""
const shared = [];
const nav = { canShare: () => true, share: async () => { throw new Error("NotAllowedError"); } };""")
        self.assertEqual((out["outcome"], out["clicks"]), ("downloaded", ["my-linehound.png"]))

    def test_the_words_in_the_module_use_no_claim_words(self):
        text = (JS / "share-card.js").read_text(encoding="utf-8")
        pairs = re.findall(r'"([^"\n]{3,})"|`([^`\n]{3,})`', text)
        literals = " ".join(x or y for x, y in pairs)
        self.assertIsNone(re.search(r"(?i)\block\b|guarantee|can'?t lose|sure thing|free money|\bedge\b|\bprofit|bet check|\bbeta\b", literals))
        self.assertIn("mountShareButton", text)


class TheImageShipsTheFontsAndPillow(unittest.TestCase):
    """2026-10-20: a served file must be in the image in the same commit that adds the reader (twice burned)."""

    def test_the_dockerfile_copies_src_and_the_build_context_admits_the_fonts(self):
        from tests.test_image_ships_ufc_data import _rules, excluded_from_build_context
        dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, re.compile(r"^COPY src/ src/\s*$", re.M))
        rules = _rules(ROOT / ".dockerignore")
        fonts = sorted((ROOT / "src" / "hounds" / "share_assets").glob("*.ttf"))
        self.assertGreaterEqual(len(fonts), 3)
        for font in fonts:
            self.assertFalse(excluded_from_build_context(font.relative_to(ROOT).as_posix(), rules), font.name)

    def test_pillow_is_a_pinned_api_requirement(self):
        reqs = (ROOT / "api" / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(reqs, re.compile(r"^Pillow==\d+\.\d+\.\d+\s*$", re.M))

    def test_the_renderer_imports_pillow_lazily_so_ci_without_it_still_loads_the_card(self):
        head = (ROOT / "src" / "hounds" / "share_card.py").read_text(encoding="utf-8").split("class RenderUnavailable")[0]
        self.assertNotRegex(head, re.compile(r"^(from|import) (PIL|fastapi)", re.M))
        self.assertNotRegex(head, re.compile(r"^from src.hounds import .*share_render", re.M))


if __name__ == "__main__":
    unittest.main()
