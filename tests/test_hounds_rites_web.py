"""The two owner rites on the pages, run for real under node against the pages' own HTML (tests/hounds_web_harness.mjs):

  * THE RENAME  the run-it-now preview is "Unleash" everywhere a person reads; nothing labels it "Take them out back".
  * OUT BACK    tap, a sheet ("This is permanent. Your hound is buried and its record is frozen."), a SECOND sheet, and only the
                second button sends the request, with {"confirm": true}; then the burial reveal and the dog leaves the kennel.
  * TRAINING    one sheet, a short montage (skipped under prefers-reduced-motion), then the "what changed and why" card.
  * MENU        Unleash, Send to training and Take them out back together on the dog page (owner only) and on the kennel card.
  * GRAVEYARD   web/graveyard.html, the Graveyard section of a kennel page, and a buried dog's headstone on its own page.

The server payloads the pages read are made by the real Python (outback.bury, training.train) over a temp database, so a
drift between the server and the page fails here and not in front of a member.

Skipped when node is not installed (the static checks need none).
"""

from __future__ import annotations

import json
import re
import unittest

from src.hounds.interact import outback, training
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for
from tests import test_backtest_kennel_web as copy_tests          # modules, not classes: pytest would collect an imported TestCase twice
from tests import test_hounds_interact_web as interact_web
from tests import test_kennel_page as kennel_tests
from tests.hounds_web_runner import HAS_NODE, WEB, run_page

HID, Payloads, dog_routes, hook, page, q = (interact_web.HID, interact_web.Payloads, interact_web.dog_routes, interact_web.hook,
                                            interact_web.page, interact_web.q)
SIGNED, dog, mine, public = kennel_tests.SIGNED, kennel_tests.dog, kennel_tests.mine, kennel_tests.public
NoFireNowLeftInTheWords = copy_tests.NoFireNowLeftInTheWords

MIXED = [(7, dict(result="LOSS", side="away", price=180)), (2, dict(result="WIN", side="away", price=180)),
         (6, dict(result="WIN", side="home", price=110, sport="NFL")), (3, dict(result="LOSS", side="home", price=110, sport="NFL"))]
WARNING = "This is permanent. Your hound is buried and its record is frozen."


class World(RitesCase):
    """The real payloads, once: a trained dog's card and a buried dog's headstone."""
    runTest = lambda self: None            # noqa: E731 -- a TestCase used as a fixture, never run

    @classmethod
    def build(cls):
        w = cls()
        w.setUp()
        try:
            hound = w.dog("Rusty Pup", sports=["MLB", "NFL"])
            trained = training.train(w.resolve(hound["id"]), w.owner.id, confirmed=True, now=NOW, rows=rows_for(hound["id"], MIXED),
                                     env={}, background=False)
            light = training.train(w.resolve(w.dog("Young Pup", sports=["MLB", "NFL"])["id"]), w.owner.id, confirmed=True, now=NOW,
                                   rows=[], env={}, background=False)
            gone = w.dog("Steam Pup", side_rule="market_moved_toward")
            buried = outback.bury(w.resolve(gone["id"]), w.owner.id, confirmed=True, now=NOW,
                                  rows=rows_for(gone["id"], [(7, dict(result="LOSS", side="away", price=150)), (3, dict(result="WIN", side="away", price=150)),
                                                             (2, dict(result="LOSS", side="home", price=-110))]))
            second = w.dog("Other Pup", owner=w.other)
            other = outback.bury(w.resolve(second["id"]), w.other.id, confirmed=True, now=NOW, rows=[])
            return {k: json.loads(json.dumps(v)) for k, v in {"trained": trained, "light": light, "buried": buried, "other": other}.items()}
        finally:
            w.doCleanups()


_PAYLOADS = {}


def payloads():
    if not _PAYLOADS:
        _PAYLOADS.update(World.build())
    return _PAYLOADS


def click(sel, label, wait=250, capture=None, **kw):
    return dict(do="click", sel=sel, label=label, wait=wait, capture=capture or [], **kw)


def sheet_caps():
    return [q("sheet", ".rt-sheet", "count"),
            q("layers", hook("rites-layer"), "count"), q("title", hook("rites-title")), q("warn", hook("outback-warning")), q("second", hook("outback-second")),
            q("buttons", hook("rites-actions") + " button", "texts"), q("refused", hook("outback-refused")), q("trefused", hook("training-refused")),
            q("motion", ".rt-sheet", "attr", attr="data-motion"), q("kind", ".rt-sheet", "attr", attr="data-hook")]


def kennel_routes(dogs, **over):
    r = kennel_tests.TheStudio().routes(dogs)
    r["POST /hounds/u-1/out-back"] = [200, payloads()["buried"]]
    r["POST /hounds/u-1/train"] = [200, payloads()["trained"]]
    r.update(over)
    return r


# ---------------------------------------------------------------------------------------------------
# the rename: static
# ---------------------------------------------------------------------------------------------------

class NothingLabelsThePreviewTakeThemOutBack(unittest.TestCase):
    scan = NoFireNowLeftInTheWords()
    PREVIEW_SCRIPTS = ("dog-fire.js", "dog-camp.js", "live-board.js", "dog-manual.js", "dog-kit.js", "hounds-detail.js", "dog-ask.js", "dog-backtest.js")
    OUT_BACK = re.compile(r"out back", re.I)

    def test_no_preview_script_says_out_back_in_its_words(self):
        for name in self.PREVIEW_SCRIPTS:
            path = WEB / "js" / name
            if not path.exists():
                continue
            with self.subTest(script=name):
                self.assertEqual([t for t in self.scan.literals(path) if self.OUT_BACK.search(t)], [], name)

    def test_the_pages_that_hold_the_preview_do_not_say_out_back(self):
        # (not landing.html: its "Train it or take it out back" step describes the product, it does not label the preview)
        for name in ("hound.html", "learning.html", "live.html", "hounds.html", "kennels.html", "desk.html", "build-a-hound.html"):
            with self.subTest(page=name):
                self.assertEqual(self.OUT_BACK.findall(self.scan.visible_html(name)), [], name)

    def test_the_kennel_pages_only_say_it_for_the_burial(self):
        for name in ("kennel.html",):
            self.assertEqual(self.OUT_BACK.findall(self.scan.visible_html(name)), [])
        literals = [t for t in self.scan.literals(WEB / "js" / "kennel.js") if self.OUT_BACK.search(t)]
        self.assertTrue(literals)
        for text in literals:
            self.assertNotRegex(text, r"(?i)picks|preview|fire|bet right now", text)

    def test_the_words_a_person_reads_are_unleash(self):
        fire = (WEB / "js" / "dog-fire.js").read_text(encoding="utf-8")
        self.assertIn('text: "Unleash"', fire)
        self.assertIn("See what it would pick", fire)          # the visitor's read-only preview has its own name (2026-10-22)
        self.assertIn("Unleashing", (WEB / "js" / "dog-camp.js").read_text(encoding="utf-8"))
        self.assertIn('text: "Unleash"', (WEB / "js" / "dog-camp.js").read_text(encoding="utf-8").replace('"data-hook": "camp-dog-fire", ', ""))
        self.assertIn(">Unleash<", (WEB / "hound.html").read_text(encoding="utf-8"))
        self.assertIn('role="tab" data-tab="fire" aria-selected="false">Unleash<', (WEB / "kennel.html").read_text(encoding="utf-8"))

    def test_the_route_and_the_hooks_keep_the_old_word(self):
        self.assertIn("/fire`", (WEB / "js" / "dog-fire.js").read_text(encoding="utf-8"))
        self.assertIn('"data-hook": "fire-btn"', (WEB / "js" / "dog-fire.js").read_text(encoding="utf-8"))
        self.assertIn('"data-hook": "dog-action-fire"', (WEB / "js" / "kennel.js").read_text(encoding="utf-8"))

    def test_the_voice_guide_says_so(self):
        voice = (WEB.parent / "docs" / "VOICE.md").read_text(encoding="utf-8")
        for needle in ("Unleash", "Take them out back", "Send to training", "Graveyard", "Its new record starts now"):
            self.assertIn(needle, voice)


class TheNewPagesCarryTheHardLines(unittest.TestCase):
    PAGES = ("graveyard.html", "hound.html", "kennel.html")

    def test_21_plus_the_helpline_and_the_paper_notice_are_in_the_static_markup(self):
        for name in self.PAGES:
            html = (WEB / name).read_text(encoding="utf-8")
            with self.subTest(page=name):
                self.assertIn("21+", html)
                self.assertIn("1-800-GAMBLER", html)
                self.assertIn('href="tel:1-800-426-2537"', html)
                self.assertIn("Paper bets", html)      # # owner ruling 2026-10-20 kennel-first: "21+ · Paper bets only, not advice · Bet at your own risk" in the footer

    def test_no_bet_check_and_no_banned_word_on_the_new_surface(self):
        banned = re.compile(r"bet ?check|\block\b|guarantee|sure thing|can'?t lose|free money|\bprofit|\bedge\b", re.I)
        scan = NoFireNowLeftInTheWords()
        for path in (WEB / "graveyard.html", WEB / "js" / "graveyard.js", WEB / "js" / "dog-rites.js", WEB / "js" / "dog-headstone.js"):
            text = " ".join(scan.visible_html(path.name) if path.suffix == ".html" else scan.literals(path))
            with self.subTest(file=path.name):
                self.assertIsNone(banned.search(text), banned.search(text))

    def test_the_graveyard_page_has_the_one_navigation_and_the_motion_script(self):
        html = (WEB / "graveyard.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="lh-nav"'), 1)
        self.assertIn('<script type="module" src="js/nav.js"></script>', html)
        self.assertIn('<script type="module" src="js/fx.js"></script>', html)
        self.assertIn('data-nav="leaderboard" aria-current="page"', html)      # # owner ruling 2026-10-20 kennel-first: the Graveyard hangs off the Leaderboard

    def test_every_new_animation_is_inside_the_no_preference_block(self):
        css = re.sub(r"/\*.*?\*/", "", (WEB / "css" / "dog-kit.css").read_text(encoding="utf-8"), flags=re.S)
        rest = kennel_tests.EveryAnimationIsInsideNoPreference.outside_motion_blocks(css)
        self.assertNotRegex(rest, r"animation(-name)?\s*:")
        for name in ("rt-fade", "rt-rise", "rt-lower"):
            self.assertIn(f"@keyframes {name}", css)
        # the evolution's stylesheet (css/evolve.css, imported by dog-kit.css) holds to the same rule
        evolve = re.sub(r"/\*.*?\*/", "", (WEB / "css" / "evolve.css").read_text(encoding="utf-8"), flags=re.S)
        self.assertNotRegex(kennel_tests.EveryAnimationIsInsideNoPreference.outside_motion_blocks(evolve), r"(animation(-name)?|transition)\s*:")
        self.assertIn('@import url("evolve.css")', css)
        for name in ("ev-streak", "ev-flash", "ev-strike", "ev-land"):
            self.assertIn(f"@keyframes {name}", evolve)


# ---------------------------------------------------------------------------------------------------
# the kennel card
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennelCardOffersTheThreeTogether(unittest.TestCase):
    def test_unleash_send_to_training_and_take_them_out_back_sit_together_and_out_back_is_the_destructive_one(self):
        out = run_page("kennel", routes=kennel_routes([dog("u-1")]), **SIGNED, queries=[
            q("actions", "[data-hook='kennel-dog'] .kn-act", "texts"),
            q("danger", ".kn-act--danger", "texts"), q("danger_hook", ".kn-act--danger", "attr", attr="data-hook"),
            q("primary", ".kn-act--primary", "texts"), q("aria", "[data-hook='dog-action-outback']", "attr", attr="aria-label")])
        f = out["final"]
        # # owner ruling 2026-10-20 kennel-first: the card offers the three rites and Edit (Ask, Open and Remove moved into the studio and the name link)
        self.assertEqual(f["actions"], ["Unleash", "Send to training", "Edit", "Take them out back"])
        self.assertEqual((f["danger"], f["danger_hook"], f["primary"]), (["Take them out back"], "dog-action-outback", ["Unleash"]))
        self.assertEqual(f["aria"], "Take Underdog Gus out back")

    def test_a_trained_dog_wears_its_badge_on_the_card(self):
        out = run_page("kennel", routes=kennel_routes([dog("u-1", trained_times=2, version_no=3)]), **SIGNED,
                       queries=[q("badge", "[data-hook='kennel-dog'] [data-hook='trained-badge']", "texts")])
        self.assertEqual(out["final"]["badge"], ["Trained ×2"])

    def test_a_retired_dog_gets_no_rites(self):
        out = run_page("kennel", routes=kennel_routes([dog("u-2", status="retired", retired=True)]), **SIGNED,
                       queries=[q("train", hook("dog-action-train"), "count"), q("out", hook("dog-action-outback"), "count")])
        self.assertEqual((out["final"]["train"], out["final"]["out"]), (0, 0))

    def test_a_public_kennel_shows_no_rites_at_all(self):
        out = run_page("kennel", routes={"/hounds/kennels/handler-21e8": public([dog("u-1")]), "/hounds/stream?page=1&page_size=60": [200, {"items": []}]},
                       search="?u=handler-21e8", queries=[q("train", hook("dog-action-train"), "count"), q("out", hook("dog-action-outback"), "count")])
        self.assertEqual((out["final"]["train"], out["final"]["out"]), (0, 0))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TakeThemOutBackAsksTwiceThenBuries(unittest.TestCase):
    OPEN = "[data-hook='dog-action-outback']"

    def run_flow(self, routes, actions, **kw):
        return run_page("kennel", routes=routes, **SIGNED, reducedMotion=kw.pop("reducedMotion", True), actions=actions, **kw)

    def test_the_two_step_confirm_then_the_reveal_and_only_the_second_button_posts(self):
        routes = kennel_routes([dog("u-1")])
        out = self.run_flow(routes, [
            click(self.OPEN, "first", capture=sheet_caps()),
            click(hook("outback-continue"), "second", capture=sheet_caps()),
            click(hook("outback-bury"), "reveal", wait=400, capture=sheet_caps() + [
                q("epitaph", hook("headstone-epitaph")), q("name", hook("headstone-name")), q("dates", hook("headstone-dates")),
                q("record", hook("headstone-record")), q("note", hook("burial-note")), q("stone", hook("headstone"), "count"),
                q("link", hook("burial-graveyard"), "attr", attr="href")])])
        first, second, reveal = (out["captures"][k] for k in ("first", "second", "reveal"))
        self.assertEqual(first["kind"], "outback-confirm-1")
        self.assertEqual(first["title"], "Take Underdog Gus out back?")
        self.assertEqual(first["warn"], WARNING)
        self.assertEqual(first["buttons"], ["Keep Underdog Gus", "Continue"])
        self.assertEqual(second["kind"], "outback-confirm-2")
        self.assertEqual(second["title"], "Bury Underdog Gus?")
        self.assertIn("will be buried", second["second"])
        self.assertEqual(second["buttons"], ["Go back", "Bury Underdog Gus"])
        # nothing was sent until the second button
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/out-back"])
        self.assertEqual(out["posts"][0]["body"], {"confirm": True})
        stone = payloads()["buried"]["headstone"]
        self.assertEqual(reveal["kind"], "outback-reveal")
        self.assertEqual(reveal["title"], "Underdog Gus is laid to rest")
        self.assertEqual((reveal["epitaph"], reveal["name"]), (stone["epitaph"], stone["name"]))
        self.assertEqual(reveal["record"], f"{stone['record']['wins']}-{stone['record']['losses']}")
        self.assertIn("Its record is frozen", reveal["note"])
        self.assertEqual((reveal["stone"], reveal["link"]), (1, "graveyard.html"))

    def test_keeping_the_dog_at_the_first_sheet_sends_nothing(self):
        out = self.run_flow(kennel_routes([dog("u-1")]), [
            click(self.OPEN, "first"), click(hook("outback-cancel"), "after", capture=[q("layers", hook("rites-layer"), "count")])])
        self.assertEqual(out["posts"], [])
        self.assertEqual(out["captures"]["after"]["layers"], 0)

    def test_going_back_from_the_second_sheet_returns_to_the_first_and_sends_nothing(self):
        out = self.run_flow(kennel_routes([dog("u-1")]), [
            click(self.OPEN, "first"), click(hook("outback-continue"), "second"),
            click(hook("outback-back"), "back", capture=sheet_caps())])
        self.assertEqual(out["posts"], [])
        self.assertEqual((out["captures"]["back"]["kind"], out["captures"]["back"]["title"]), ("outback-confirm-1", "Take Underdog Gus out back?"))

    def test_the_scrim_closes_the_sheet_without_burying(self):
        out = self.run_flow(kennel_routes([dog("u-1")]), [
            click(self.OPEN, "first"), click(hook("rites-scrim"), "closed", capture=[q("layers", hook("rites-layer"), "count")])])
        self.assertEqual((out["posts"], out["captures"]["closed"]["layers"]), ([], 0))

    def test_a_refusal_is_shown_in_the_servers_words_and_nothing_is_revealed(self):
        refusal = [409, {"detail": {"error": "open_tickets", "message": "Underdog Gus has 1 open ticket. Wait until its open tickets settle."}}]
        routes = kennel_routes([dog("u-1")], **{"POST /hounds/u-1/out-back": refusal})
        out = self.run_flow(routes, [click(self.OPEN, "a"), click(hook("outback-continue"), "b"),
                                      click(hook("outback-bury"), "c", wait=300, capture=sheet_caps() + [q("stone", hook("headstone"), "count")])])
        cap = out["captures"]["c"]
        self.assertEqual(cap["refused"], "Underdog Gus has 1 open ticket. Wait until its open tickets settle.")
        self.assertEqual(cap["stone"], 0)
        self.assertEqual(cap["buttons"], ["Close"])

    def test_done_redraws_the_kennel_without_the_dog_and_says_so(self):
        routes = kennel_routes([dog("u-1")])
        routes_after = mine([])
        out = self.run_flow(routes, [
            click(self.OPEN, "a"), click(hook("outback-continue"), "b"), click(hook("outback-bury"), "c", wait=300),
            click(hook("burial-done"), "done", wait=500, capture=[q("layers", hook("rites-layer"), "count"), q("cards", "[data-hook='kennel-dog']", "count"),
                                                                  q("status", hook("kennel-status"))])],
            switchAfter={"/hounds/kennels/mine": [1, routes_after]})
        cap = out["captures"]["done"]
        self.assertEqual((cap["layers"], cap["cards"]), (0, 0))
        self.assertIn("was taken out back. Its record is frozen in the graveyard.", cap["status"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class SendToTrainingShowsTheMontageThenTheCard(unittest.TestCase):
    OPEN = "[data-hook='dog-action-train']"

    def run_flow(self, routes, actions, reduced=True, **kw):
        return run_page("kennel", routes=routes, **SIGNED, reducedMotion=reduced, actions=actions, **kw)

    def test_one_confirm_then_the_what_changed_and_why_card_with_the_new_version(self):
        routes = kennel_routes([dog("u-1")])
        card = [q("label", hook("training-label")), q("version", hook("training-version")), q("headline", hook("training-headline")),
                q("changes", hook("training-change"), "count"), q("change", hook("training-change")), q("guidance", hook("training-guidance")),
                q("old", hook("training-old-record")), q("new", hook("training-new-record")), q("badge", hook("training-card") + " " + hook("trained-badge")),
                q("next", hook("training-next")), q("open", hook("training-open-new"), "attr", attr="href"), q("kind", ".rt-sheet", "attr", attr="data-hook")]
        out = self.run_flow(routes, [
            click(self.OPEN, "ask", capture=sheet_caps()),
            click(hook("training-go"), "card", wait=400, capture=card)])
        ask, got = out["captures"]["ask"], out["captures"]["card"]
        self.assertEqual((ask["kind"], ask["title"]), ("training-confirm", "Send Underdog Gus to training?"))
        self.assertEqual(ask["buttons"], ["Not now", "Send to training"])
        # the diagnosis step is asked first; this fixture has no route for it, so the phase is skipped and the training goes on
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/train/diagnose", "/hounds/u-1/train"])
        self.assertEqual(out["posts"][1]["body"], {"confirm": True})
        data = payloads()["trained"]
        self.assertEqual(got["kind"], "training-reveal")
        self.assertEqual((got["label"], got["version"]), ("Trained", "Version 2"))
        self.assertEqual(got["headline"], "Rusty Pup is back as version 2. Its new record starts now.")
        self.assertEqual(got["changes"], len(data["changes"]))
        self.assertIn("Sports", got["change"])
        self.assertIn("MLB and NFL", got["change"])
        self.assertIn("9 MLB bets went 2-7", got["change"])
        self.assertEqual(got["guidance"], data["guidance"]["text"])
        self.assertEqual((got["old"], got["new"]), ("8-10", "0-0"))
        self.assertEqual(got["badge"], "Trained ×1")
        self.assertEqual(got["open"], data["new"]["page_href"])
        self.assertIn("5 new settled bets", got["next"])

    def test_the_card_never_says_the_new_version_is_better(self):
        out = self.run_flow(kennel_routes([dog("u-1")]), [click(self.OPEN, "a"), click(hook("training-go"), "b", wait=400,
                                                                                       capture=[q("card", hook("training-card"))])])
        text = out["captures"]["b"]["card"]
        self.assertIsNone(re.search(r"\b(better|improve\w*|stronger|smarter|profit\w*|will win)\b", text, re.I), text)
        self.assertIn("starts now", text)

    def test_a_light_adjustment_is_clearly_labelled(self):
        routes = kennel_routes([dog("u-1")], **{"POST /hounds/u-1/train": [200, payloads()["light"]]})
        out = self.run_flow(routes, [click(self.OPEN, "a"), click(hook("training-go"), "b", wait=400,
                                                                  capture=[q("label", hook("training-label")), q("note", hook("training-light-note")),
                                                                           q("title", hook("rites-title")), q("mode", hook("training-card"), "attr", attr="data-mode")])])
        cap = out["captures"]["b"]
        self.assertEqual((cap["label"], cap["title"], cap["mode"]), ("Light adjustment", "A light adjustment", "light"))
        self.assertIn("light adjustment", cap["note"])

    def test_not_now_sends_nothing(self):
        out = self.run_flow(kennel_routes([dog("u-1")]), [click(self.OPEN, "a"), click(hook("training-cancel"), "b", capture=[q("layers", hook("rites-layer"), "count")])])
        self.assertEqual((out["posts"], out["captures"]["b"]["layers"]), ([], 0))

    def test_a_refusal_is_shown_in_the_servers_words(self):
        refusal = [409, {"detail": {"error": "training_too_soon", "message": "Underdog Gus needs 5 new settled bets on version 2 before it can train again. It has 2."}}]
        out = self.run_flow(kennel_routes([dog("u-1")], **{"POST /hounds/u-1/train": refusal}), [
            click(self.OPEN, "a"), click(hook("training-go"), "b", wait=400, capture=sheet_caps() + [q("card", hook("training-card"), "count")])])
        cap = out["captures"]["b"]
        self.assertEqual(cap["trefused"], "Underdog Gus needs 5 new settled bets on version 2 before it can train again. It has 2.")
        self.assertEqual((cap["card"], cap["buttons"]), (0, ["Close"]))

    def test_a_refused_training_does_not_say_the_hound_is_in_training(self):
        # rebuild QA 2026-10-20: the refusal sheet kept the montage's title, "<name> is in training", above "needs 5 new settled bets"
        refusal = [409, {"detail": {"error": "training_too_soon", "message": "Underdog Gus needs 5 new settled bets on version 2 before it can train again. It has 2."}}]
        out = self.run_flow(kennel_routes([dog("u-1")], **{"POST /hounds/u-1/train": refusal}), [
            click(self.OPEN, "a"), click(hook("training-go"), "b", wait=400, capture=sheet_caps())])
        cap = out["captures"]["b"]
        self.assertNotIn("is in training", cap["title"])
        self.assertTrue(cap["title"].endswith("stays as it is"), cap["title"])
        self.assertEqual(cap["kind"], "training-refused-sheet")

    def test_with_reduced_motion_the_card_is_there_at_once_and_the_sheet_says_so(self):
        out = self.run_flow(kennel_routes([dog("u-1", version_no=1)]), [
            click(self.OPEN, "a", capture=[q("motion", ".rt-sheet", "attr", attr="data-motion")]),
            click(hook("training-go"), "b", wait=120, capture=[q("card", hook("training-card"), "count"), q("phase", hook("evolve"), "attr", attr="data-phase"),
                                                              q("pair", hook("evolve-pair") + " figcaption", "texts"), q("skip", hook("evolve-skip"), "count"),
                                                              q("stats", hook("evolve-stat"), "count"), q("title", hook("evolve-title"))])])
        self.assertEqual(out["captures"]["a"]["motion"], "reduced")
        cap = out["captures"]["b"]
        # one static before-and-after card, at once: nothing waits on a timer, nothing is charged or flashed
        self.assertEqual((cap["card"], cap["phase"], cap["pair"]), (1, "static", ["v1", "v2"]))
        self.assertEqual(cap["stats"], len(payloads()["trained"]["changes"]))
        self.assertEqual(cap["title"], "Underdog Gus became Underdog Gus v2!")

    def test_with_motion_allowed_the_evolution_plays_first_and_the_card_follows(self):
        # before, charge, burst, reveal (about seven seconds), then the upgrade card; the request has long since finished
        out = self.run_flow(kennel_routes([dog("u-1", version_no=1)]), [
            click(self.OPEN, "a", capture=[q("motion", ".rt-sheet", "attr", attr="data-motion")]),
            click(hook("training-go"), "before", wait=300, capture=[q("phase", hook("evolve"), "attr", attr="data-phase"), q("card", hook("evolve-card"), "count"),
                                                                    q("badge", hook("evolve-version")), q("line", hook("training-status")),
                                                                    q("flash", hook("evolve-flash"), "count")]),
            dict(do="wait", label="charge", wait=2400, capture=[q("phase", hook("evolve"), "attr", attr="data-phase"), q("card", hook("evolve-card"), "count"),
                                                                 q("silhouettes", "[data-sil]", "count"),
                                                                 # the NEW silhouette is the v2 hound (its bandana is drawn in it); the OLD one is the v1 hound (nothing worn)
                                                                 q("newGear", ".ev-hound--new[data-sil] .dk-tier--bandana", "count"), q("oldGear", ".ev-hound--old[data-sil] .dk-tier--bandana", "count"),
                                                                 q("newVno", ".ev-hound--new", "attr", attr="data-vno"), q("oldVno", ".ev-hound--old", "attr", attr="data-vno")]),
            dict(do="wait", label="card", wait=6200, capture=[q("phase", hook("evolve"), "attr", attr="data-phase"), q("card", hook("evolve-card"), "count"),
                                                               q("title", hook("evolve-title")), q("tier", hook("evolve-tier")),
                                                               q("stats", hook("evolve-stat"), "count")])], reduced=False)
        caps = out["captures"]
        self.assertEqual(caps["a"]["motion"], "full")
        self.assertEqual((caps["before"]["phase"], caps["before"]["card"], caps["before"]["badge"]), ("before", 0, "v1"))
        # the one line is the server's own change list, never invented
        data = payloads()["trained"]
        for change in data["changes"]:
            self.assertIn(change["new_text"], caps["before"]["line"])
        self.assertTrue(caps["before"]["line"].startswith("Training changed:"), caps["before"]["line"])
        self.assertEqual((caps["charge"]["phase"], caps["charge"]["card"]), ("charge", 0))
        self.assertEqual(caps["charge"]["silhouettes"], 2)
        self.assertEqual((caps["charge"]["oldVno"], caps["charge"]["newVno"]), ("1", "2"))
        self.assertEqual((caps["charge"]["oldGear"], caps["charge"]["newGear"]), (0, 1), "the new silhouette carries the new tier's own gear, the old one does not")
        self.assertEqual((caps["card"]["phase"], caps["card"]["card"]), ("card", 1))
        self.assertEqual(caps["card"]["title"], "Underdog Gus became Underdog Gus v2!")
        self.assertEqual(caps["card"]["tier"], "v2 \u00b7 Bronze")
        self.assertEqual(caps["card"]["stats"], len(data["changes"]))

    def test_a_tap_after_the_first_second_skips_to_the_card_and_a_tap_before_does_not(self):
        out = self.run_flow(kennel_routes([dog("u-1", version_no=1)]), [
            click(self.OPEN, "a"),
            click(hook("training-go"), "early", wait=200),
            click(hook("evolve-stage"), "tapped_early", wait=100, capture=[q("phase", hook("evolve"), "attr", attr="data-phase"), q("card", hook("evolve-card"), "count")]),
            dict(do="wait", label="later", wait=1000),
            click(hook("evolve-skip"), "skipped", wait=150, capture=[q("phase", hook("evolve"), "attr", attr="data-phase"), q("card", hook("evolve-card"), "count"),
                                                                     q("skipped", hook("evolve"), "attr", attr="data-skipped")])], reduced=False)
        caps = out["captures"]
        self.assertEqual((caps["tapped_early"]["phase"], caps["tapped_early"]["card"]), ("before", 0))
        self.assertEqual((caps["skipped"]["phase"], caps["skipped"]["card"], caps["skipped"]["skipped"]), ("card", 1, "1"))

    def test_the_old_what_changed_and_why_card_is_folded_under_the_upgrade_card(self):
        out = self.run_flow(kennel_routes([dog("u-1")]), [click(self.OPEN, "a"), click(hook("training-go"), "b", wait=300,
                                                                                       capture=[q("fold", hook("evolve-why") + " " + hook("training-card"), "count"),
                                                                                                q("see", hook("training-open-new"), "texts"), q("back", hook("training-done"), "texts")])])
        cap = out["captures"]["b"]
        self.assertEqual(cap["fold"], 1)
        self.assertEqual((cap["see"], cap["back"]), (["See v2"], ["Back to My Kennel"]))

    def test_a_failed_request_ends_with_the_error_and_no_upgrade_is_ever_drawn(self):
        refusal = [409, {"detail": {"error": "training_too_soon", "message": "Underdog Gus needs 5 new settled bets on version 1 before it can train again. It has 2."}}]
        out = self.run_flow(kennel_routes([dog("u-1", version_no=1)], **{"POST /hounds/u-1/train": refusal}), [
            click(self.OPEN, "a"),
            click(hook("training-go"), "b", wait=250, capture=[q("evolve", hook("evolve"), "count"), q("card", hook("evolve-card"), "count"),
                                                              q("new", ".ev-hound--new", "count"), q("refused", hook("training-refused")),
                                                              q("title", hook("rites-title")), q("kind", ".rt-sheet", "attr", attr="data-hook")]),
            dict(do="wait", label="later", wait=2600, capture=[q("card", hook("evolve-card"), "count"), q("evolve", hook("evolve"), "count"), q("refused", hook("training-refused"))])],
            reduced=False)
        b, later = out["captures"]["b"], out["captures"]["later"]
        self.assertEqual((b["evolve"], b["card"], b["new"]), (0, 0, 0))
        self.assertIn("needs 5 new settled bets", b["refused"])
        self.assertEqual(b["kind"], "training-refused-sheet")
        self.assertTrue(b["title"].endswith("stays as it is"), b["title"])
        self.assertEqual((later["card"], later["evolve"]), (0, 0))
        self.assertEqual(later["refused"], b["refused"])

    def test_the_sequence_waits_for_a_slow_server_and_draws_no_upgrade_before_it_answers(self):
        out = self.run_flow(kennel_routes([dog("u-1", version_no=1)]), [
            click(self.OPEN, "a"),
            click(hook("training-go"), "b", wait=2600, capture=[q("phase", hook("evolve"), "attr", attr="data-phase"), q("card", hook("evolve-card"), "count"),
                                                                q("new", ".ev-hound--new", "count"), q("badge", hook("evolve-version"))])],
            reduced=False, delay={"/hounds/u-1/train": 4000})
        cap = out["captures"]["b"]
        # past the 1.9 s a free server would have taken, the beat holds on "Training..." with the old hound and no new one
        self.assertEqual((cap["phase"], cap["card"], cap["new"], cap["badge"]), ("before", 0, 0, "v1"))

    def test_done_redraws_the_kennel_with_the_new_version_and_its_badge(self):
        trained_card = dog("u-9", "Underdog Gus", version_no=2, trained_times=1)
        routes = kennel_routes([dog("u-1")])
        out = self.run_flow(routes, [click(self.OPEN, "a"), click(hook("training-go"), "b", wait=400),
                                      click(hook("training-done"), "done", wait=500, capture=[q("layers", hook("rites-layer"), "count"),
                                                                                               q("badge", "[data-hook='kennel-dog'] [data-hook='trained-badge']", "texts"),
                                                                                               q("status", hook("kennel-status"))])],
                            switchAfter={"/hounds/kennels/mine": [1, mine([trained_card])]})
        cap = out["captures"]["done"]
        self.assertEqual((cap["layers"], cap["badge"]), (0, ["Trained ×1"]))
        self.assertIn("is back as version 2. Its new record starts now.", cap["status"])


# ---------------------------------------------------------------------------------------------------
# the dog page
# ---------------------------------------------------------------------------------------------------

def owner_kit(**over):
    return Payloads.kit(owner=True, **{"can_train": True, "can_out_back": True, "trained_times": 0, "coached_from": None, "buried": False, **over})


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheOwnersHoundMenuOnTheDogPage(unittest.TestCase):
    def test_the_owner_gets_the_three_together_in_one_menu_and_the_destructive_one_is_marked(self):
        out = page(dog_routes(kit=owner_kit()), queries=[
            q("section", hook("dog-rites-section"), "hidden"), q("title", "#rites-h"), q("buttons", hook("dog-menu") + " button", "texts"),
            q("danger", hook("menu-outback"), "attr", attr="class"), q("aria", hook("menu-train"), "attr", attr="aria-label"), q("fire", "#fire-h")])
        f = out["final"]
        self.assertEqual((f["section"], f["title"]), (False, "Your hound"))
        self.assertEqual(f["buttons"], ["Unleash", "Send to training", "Take them out back"])
        self.assertIn("btn--danger", f["danger"])
        self.assertEqual((f["aria"], f["fire"]), ("Send Closer to training", "Unleash"))

    def test_a_visitor_who_does_not_own_the_dog_sees_no_menu(self):
        for kit_ in (Payloads.kit(owner=False), Payloads.kit(owner=False, signed_in=False)):
            out = page(dog_routes(kit=kit_), queries=[q("section", hook("dog-rites-section"), "hidden"), q("menu", hook("dog-menu"), "count")])
            self.assertEqual((out["final"]["section"], out["final"]["menu"]), (True, 0))

    def test_the_menus_unleash_is_the_real_one_that_starts_the_hound_today(self):
        # 2026-10-22: the owner's Unleash on the hound page is the studio's (POST /unleash), not the read-only preview (POST /fire)
        out = page(dog_routes(kit=owner_kit()), actions=[click(hook("menu-unleash"), "go", wait=300, capture=[q("headline", hook("unleash-headline")), q("btn", hook("fire-btn"))])])
        self.assertEqual([p["url"] for p in out["posts"]], [f"/hounds/{HID}/unleash"])
        self.assertIn("unleashed", out["captures"]["go"]["headline"])
        self.assertEqual(out["captures"]["go"]["btn"], "Unleash")

    def test_burying_from_the_dog_page_goes_back_to_its_page_for_the_headstone(self):
        routes = dog_routes(kit=owner_kit())
        routes[f"POST /hounds/{HID}/out-back"] = [200, payloads()["buried"]]
        out = page(routes, reducedMotion=True, actions=[
            click(hook("menu-outback"), "a", capture=[q("warn", hook("outback-warning"))]), click(hook("outback-continue"), "b"),
            click(hook("outback-bury"), "c", wait=300), click(hook("burial-done"), "d", wait=200)])
        self.assertEqual(out["captures"]["a"]["warn"], WARNING)
        self.assertEqual([p["url"] for p in out["posts"]], [f"/hounds/{HID}/out-back"])
        self.assertEqual(out["navigations"][-1], f"hound.html?id={HID}")

    def test_training_from_the_dog_page_goes_to_the_new_version(self):
        routes = dog_routes(kit=owner_kit())
        routes[f"POST /hounds/{HID}/train"] = [200, payloads()["trained"]]
        out = page(routes, reducedMotion=True, actions=[click(hook("menu-train"), "a"), click(hook("training-go"), "b", wait=300,
                                                                                            capture=[q("see", hook("training-open-new"), "attr", attr="href")]),
                                                         click(hook("training-done"), "c", wait=200)])
        # "See v2" is a link to the new version; "Back to My Kennel" leaves the hound page for the kennel
        self.assertEqual(out["captures"]["b"]["see"], payloads()["trained"]["new"]["page_href"])
        self.assertEqual(out["navigations"][-1], "kennel.html")

    def test_a_dog_that_was_trained_wears_the_badge_in_its_header(self):
        out = page(dog_routes(kit=owner_kit(trained_times=2)), queries=[q("badge", ".hd-modelhead " + hook("trained-badge"), "texts")])
        self.assertEqual(out["final"]["badge"], ["Trained ×2"])
        out = page(dog_routes(kit=owner_kit()), queries=[q("badge", hook("trained-badge"), "count")])
        self.assertEqual(out["final"]["badge"], 0)

    def test_the_owner_sees_the_menu_but_only_the_server_decides(self):
        refusal = [409, {"detail": {"error": "open_tickets", "message": "Closer has 1 open ticket. Wait until its open tickets settle."}}]
        routes = dog_routes(kit=owner_kit())
        routes[f"POST /hounds/{HID}/train"] = refusal
        out = page(routes, reducedMotion=True, actions=[click(hook("menu-train"), "a"), click(hook("training-go"), "b", wait=300,
                                                                                            capture=[q("msg", hook("training-refused"))])])
        self.assertEqual(out["captures"]["b"]["msg"], "Closer has 1 open ticket. Wait until its open tickets settle.")


@unittest.skipUnless(HAS_NODE, "node not installed")
class ABuriedDogsPageShowsItsHeadstone(unittest.TestCase):
    def buried_routes(self):
        stone = payloads()["buried"]["headstone"]
        kit_ = Payloads.kit(owner=True, status="buried", can_fire=False, can_record_manual=False, can_train=False, can_out_back=False, buried=True,
                            trained_times=1)
        routes = dog_routes(kit=kit_)
        routes[f"/hounds/{HID}/headstone"] = [200, {"headstone": stone, "paper_only": True}]
        return routes, stone

    def test_the_headstone_panel_shows_the_frozen_record_and_the_epitaph(self):
        routes, stone = self.buried_routes()
        out = page(routes, queries=[
            q("section", hook("dog-headstone-section"), "hidden"), q("epitaph", hook("headstone-epitaph")), q("record", hook("headstone-record")),
            q("bank", hook("headstone-bankroll")), q("best", hook("headstone-bestwin")), q("dates", hook("headstone-dates")),
            q("frozen", hook("headstone-frozen")), q("rites", hook("dog-rites-section"), "hidden"), q("fire", hook("dog-fire-section"), "hidden"),
            q("kennel", hook("headstone-kennel"), "attr", attr="href")])
        f = out["final"]
        self.assertEqual(f["section"], False)
        self.assertEqual(f["epitaph"], stone["epitaph"])
        self.assertEqual(f["record"], f"{stone['record']['wins']}-{stone['record']['losses']}")
        self.assertTrue(f["bank"].startswith("$"))
        self.assertEqual(f["frozen"], "Record frozen")
        self.assertEqual((f["rites"], f["fire"]), (True, True))             # nothing left to do with a buried dog
        self.assertEqual(f["kennel"], stone["kennel"]["href"])

    def test_a_live_dog_never_asks_for_a_headstone(self):
        out = page(dog_routes(kit=owner_kit()), queries=[q("section", hook("dog-headstone-section"), "hidden")])
        self.assertTrue(out["final"]["section"])
        self.assertNotIn(f"/hounds/{HID}/headstone", out["gets"])


# ---------------------------------------------------------------------------------------------------
# the graveyard
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class TheGraveyardPage(unittest.TestCase):
    def go(self, stones, **kw):
        routes = {"/hounds/graveyard": [200, {"hounds": [], "headstones": stones, "paper_only": True}]}
        return run_page("graveyard", routes=routes, **kw)

    def test_every_kennels_buried_dogs_in_the_order_the_server_sent_them(self):
        a, b = payloads()["buried"]["headstone"], payloads()["other"]["headstone"]
        out = self.go([b, a], queries=[
            q("count", hook("graveyard-count")), q("names", hook("headstone-name"), "texts"), q("epitaphs", hook("headstone-epitaph"), "texts"),
            q("kennels", hook("headstone-kennel"), "texts"), q("records", hook("headstone-record"), "texts"), q("empty", hook("graveyard-empty"), "count"),
            q("hrefs", hook("headstone-name"), "attrs", attr="href"), q("h1", "h1")])
        f = out["final"]
        self.assertEqual((f["h1"], f["count"]), ("Graveyard", "2 headstones"))
        self.assertEqual(f["names"], ["Other Pup", "Steam Pup"])
        self.assertEqual(f["epitaphs"], [b["epitaph"], a["epitaph"]])
        self.assertEqual(f["empty"], 0)
        self.assertEqual(f["hrefs"][1], a["page_href"])
        self.assertEqual(f["kennels"], [b["kennel"]["display"], a["kennel"]["display"]])
        self.assertNotEqual(a["kennel"]["display"], b["kennel"]["display"])          # two members, two kennels, one graveyard

    def test_one_headstone_says_headstone_not_headstones(self):
        out = self.go([payloads()["buried"]["headstone"]], queries=[q("count", hook("graveyard-count"))])
        self.assertEqual(out["final"]["count"], "1 headstone")

    def test_an_empty_graveyard_says_so(self):
        out = self.go([], queries=[q("empty", hook("graveyard-empty")), q("count", hook("graveyard-count"))])
        self.assertIn("Nothing buried yet", out["final"]["empty"])
        self.assertEqual(out["final"]["count"], "0 headstones")

    def test_an_older_server_without_headstones_is_the_empty_graveyard_not_an_error(self):
        out = run_page("graveyard", routes={"/hounds/graveyard": [200, {"hounds": []}]}, queries=[q("empty", hook("graveyard-empty"), "count")])
        self.assertEqual(out["final"]["empty"], 1)

    def test_a_server_that_is_down_is_said_plainly(self):
        out = run_page("graveyard", routes={}, down=["/hounds/graveyard"], queries=[q("state", hook("section-state"))])
        self.assertTrue(out["final"]["state"])

    def test_the_paper_notice_and_the_helpline_are_on_the_page(self):          # in the footer, said once (owner ruling 2026-10-20 kennel-first)
        out = self.go([], queries=[q("notice", hook("footer-legal")), q("help", hook("responsible-gambling-help"), "attr", attr="href")])
        self.assertIn("21+", out["final"]["notice"])
        self.assertEqual(out["final"]["help"], "tel:1-800-426-2537")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennelPagesGraveyardSection(unittest.TestCase):
    def test_my_kennel_lists_my_buried_dogs_and_a_buried_dog_is_not_in_the_grid(self):
        stone = payloads()["buried"]["headstone"]
        data = mine([dog("u-1")])
        data[1]["graveyard"] = [stone]
        out = run_page("kennel", routes=kennel_routes([dog("u-1")], **{"/hounds/kennels/mine": data}), **SIGNED, queries=[
            q("title", "#kn-grave-h"), q("stones", hook("kennel-graveyard-list") + " " + hook("headstone-name"), "texts"), q("cards", "[data-hook='kennel-dog']", "count"),
            q("link", hook("kennel-graveyard-link"), "attr", attr="href")])
        f = out["final"]
        self.assertEqual((f["title"], f["stones"], f["cards"], f["link"]), ("Graveyard", ["Steam Pup"], 1, "graveyard.html"))

    def test_a_public_kennel_shows_the_section_too_and_an_empty_one_says_so(self):
        stone = payloads()["buried"]["headstone"]
        for stones, want in (([stone], ["Steam Pup"]), ([], [])):
            data = public([dog("u-1")])
            data[1]["graveyard"] = stones
            out = run_page("kennel", routes={"/hounds/kennels/handler-21e8": data, "/hounds/stream?page=1&page_size=60": [200, {"items": []}]},
                           search="?u=handler-21e8", queries=[q("stones", hook("headstone-name"), "texts"), q("empty", hook("kennel-graveyard-empty"), "count")])
            with self.subTest(stones=len(stones)):
                self.assertEqual(out["final"]["stones"], want)
                self.assertEqual(out["final"]["empty"], 0 if stones else 1)

    def test_a_kennel_whose_dogs_are_all_buried_still_draws_its_page(self):
        data = public([])
        data[1]["graveyard"] = [payloads()["buried"]["headstone"]]
        out = run_page("kennel", routes={"/hounds/kennels/handler-21e8": data, "/hounds/stream?page=1&page_size=60": [200, {"items": []}]},
                       search="?u=handler-21e8", queries=[q("stones", hook("headstone-name"), "texts")])
        self.assertEqual(out["final"]["stones"], ["Steam Pup"])


if __name__ == "__main__":
    unittest.main()
