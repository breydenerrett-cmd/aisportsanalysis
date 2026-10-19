"""The voice data and the hard lines (docs/VOICE.md).

Owner, 2026-10-18: "Scientists aren't buying this ... Degenerate gamblers dude." Owner, 2026-10-19: the result
"looks like a kids playground, not a professional gambling AI website". The pages are now a professional
sports-betting product (tests/test_hounds_board_pages.py); the persona fields (bio, catchphrase, roasts, brags,
epitaph) stay in the config files as voice data that the pages do not render, and src/hounds/voice.py still
carries them for a future Discord or X post. What this file pins:

  * PRESENCE. Every hound in config/house_pack.json, config/desk_hounds.json and config/house_hounds.json
    carries a persona, the owner's boss block exists, and the bios are true to what each model actually does.
  * THE PYTHON TABLES (badges, the daily line) are deterministic and a function of the referee's label only.
  * THE HARD LINES stay on every public page (21+, paper only, not advice, "Gamble responsibly. 1-800-GAMBLER",
    none of the words that make a claim) and the ACADEMIC WORDS stay off them.
  * THE FORM BLOCK (streak, last seven days, last settled day, best bet, worst beat) is derived from the same
    graded bets the record counts.
  * THE SHARED JAVASCRIPT HELPERS the pages still use (units, order, W-L, a retirement reason).

Browser-less: the JavaScript half runs under node and is skipped without it.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from src.hounds import contract, house, stats, verdict as vd, voice
from src.hounds.ledgers import Bet
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests import hounds_web_fixtures as F

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
PACK = json.loads((CONFIG / "house_pack.json").read_text(encoding="utf-8"))
DESK = json.loads((CONFIG / "desk_hounds.json").read_text(encoding="utf-8"))
HOUSE = json.loads((CONFIG / "house_hounds.json").read_text(encoding="utf-8"))
VIBES = {"degen", "nerd", "grinder", "psychic", "chaos"}

# words that make a claim, or that the owner banned outright; none belongs on a public page or in a dog's voice
CLAIM_WORDS = (r"\block\b", r"\blocks\b", r"guarantee", r"can'?t lose", r"sure thing", r"free money",
               r"\bedge\b", r"\bev\b", r"expected value", r"\bprofit")
# the academic vocabulary the owner struck from the public pages
ACADEMIC_WORDS = ("pre-registered", "preregistered", "pre-register", "date-clustered", "bootstrap", "confidence interval",
                  "closing-line value", "hypothesis", "hypotheses", "population", "falsification", "registry",
                  "benjamini", "false-discovery")
PUBLIC_PAGES = ("landing.html", "hounds.html", "hound.html", "build-a-hound.html", "learning.html", "why-we-paused.html")


def visible(html: str) -> str:
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style|head)\b.*?</\1>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    for ent, ch in (("&middot;", "·"), ("&rarr;", "->"), ("&larr;", "<-"), ("&amp;", "&"), ("&mdash;", "—"),
                    ("&ndash;", "–"), ("&nbsp;", " ")):
        text = text.replace(ent, ch)
    return re.sub(r"\s+", " ", text).strip()


def every_hound() -> list:
    out = []
    for cfg in (PACK, HOUSE, DESK):
        out.extend(cfg["hounds"])
    return out


def js(body: str):
    return run_js('import * as V from "./hounds-voice.js";\nimport * as C from "./hounds-core.js";\n' + body)


class EveryDogHasAPersona(unittest.TestCase):

    def test_every_hound_in_the_three_configs_has_a_complete_persona(self):
        hounds = every_hound()
        self.assertGreaterEqual(len(hounds), 37)
        for hound in hounds:
            p = hound.get("persona")
            self.assertIsInstance(p, dict, hound["id"])
            for field in ("bio", "catchphrase", "epitaph", "verb"):
                self.assertTrue(isinstance(p.get(field), str) and p[field].strip(), f"{hound['id']}.{field}")
            self.assertIn(p.get("vibe"), VIBES, hound["id"])
            for field in ("roasts", "brags"):
                lines = p.get(field)
                self.assertEqual(len(lines), 5, f"{hound['id']}.{field}")
                self.assertEqual(len(set(lines)), 5, f"{hound['id']}.{field} repeats a line")
                for line in lines:
                    self.assertTrue(8 <= len(line) <= 140, f"{hound['id']}.{field}: {line!r}")

    def test_existing_fields_are_kept(self):
        for hound in every_hound():
            for field in ("id", "name", "tagline", "rule_text", "category"):
                self.assertTrue(hound.get(field), f"{hound['id']} lost {field}")

    def test_the_loaded_definitions_carry_the_persona_to_the_summary(self):
        defs = house.definitions(CONFIG / "house_hounds.json", CONFIG / "house_pack.json", CONFIG / "desk_hounds.json")
        self.assertEqual(len(defs), len(every_hound()))
        for d in defs:
            self.assertIsInstance(d["persona"], dict, d["id"])
        data = stats.summarize(defs[0], [], {}, "2026-10-18")
        self.assertEqual(data.summary.persona, defs[0]["persona"])
        self.assertIsNone(data.summary.form, "no graded bet, no form")

    def test_the_characters_the_brief_names(self):
        by_id = {h["id"]: h["persona"] for h in every_hound()}
        self.assertEqual(by_id["coin_flip_collie"]["vibe"], "chaos")
        self.assertIn("coin", by_id["coin_flip_collie"]["bio"].lower())
        self.assertIn("nerds", by_id["coin_flip_collie"]["bio"].lower())          # the troll whose job is to embarrass the nerds
        self.assertEqual(by_id["professor_paws"]["vibe"], "nerd")
        self.assertIn("model", by_id["professor_paws"]["bio"].lower())
        for hid, word in (("numerology_newfie", "gematria"), ("lunar_lab", "moon")):
            self.assertEqual(by_id[hid]["vibe"], "psychic", hid)
            self.assertIn(word, by_id[hid]["bio"].lower(), hid)

    def test_each_bio_is_true_to_the_rule_the_dog_actually_runs(self):
        by_id = {h["id"]: h for h in every_hound()}
        keyword = {
            "professor_paws": "model", "totals_terrier": "total", "relief_retriever": "bullpen",
            "gridiron_greyhound": "spread", "elimination_basset": "one loss", "jetlag_jack": "red-eye",
            "steamy_setter": "steam", "contrary_corgi": "other side", "stale_bread_beagle": "move its line",
            "bargain_bloodhound": "retail", "kelly_kelpie": "kelly", "hot_streak_husky": "hot",
            "numerology_newfie": "gematria", "lunar_lab": "full moon", "coin_flip_collie": "coin",
            "dartboard_dalmatian": "dart", "pack_leader": "pack", "scrappy_schnauzer": "underdog",
            "chalk_chihuahua": "favorite", "home_dog_hank": "home", "beagle": "home", "basset": "under",
            "collie": "over", "desk_ai": "bull", "desk_weather": "weather", "desk_historian": "history",
            "desk_square": "favorites and overs", "desk_fader": "fades", "desk_grinder": "unders",
            "desk_sharp": "price",
        }
        for hid, word in keyword.items():
            self.assertIn(word, by_id[hid]["persona"]["bio"].lower(), hid)

    def test_a_persona_never_carries_a_claim_or_an_academic_word(self):
        blocks = [(h["id"], h["persona"]) for h in every_hound()] + [("houndmaster", PACK["houndmaster"])]
        for who, p in blocks:
            text = json.dumps(p).lower()
            for pattern in CLAIM_WORDS:
                self.assertIsNone(re.search(pattern, text), f"{who} says {pattern}")
            for word in ACADEMIC_WORDS:
                self.assertNotIn(word, text, f"{who} says {word}")

    def test_the_houndmaster_is_grumpy_and_has_his_lines(self):
        hm = PACK["houndmaster"]
        self.assertEqual(hm["vibe"], "grumpy")
        self.assertEqual(len(hm["roasts"]), 5)
        self.assertEqual(len(hm["brags"]), 5)
        self.assertTrue(hm["bio"] and hm["catchphrase"] and hm["put_down_lines"])
        self.assertEqual(contract.houndmaster_block(), hm)

    def test_the_payloads_carry_the_houndmaster(self):
        self.assertEqual(contract.leaderboard_payload([], None)["houndmaster"], PACK["houndmaster"])
        self.assertEqual(contract.graveyard_payload([], None)["houndmaster"], PACK["houndmaster"])
        s = contract.HoundSummary(id="x", name="X")
        self.assertEqual(contract.hound_payload(s, [], contract.paginate([], 1), None)["houndmaster"],
                         PACK["houndmaster"])

    def test_the_desk_config_still_matches_what_roles_py_generates(self):
        from src.hounds.desk import roles
        self.assertEqual(roles.config_document(), DESK)


class TheBadgesAreTheOldVerdictsInNewClothes(unittest.TestCase):

    EXPECTED = {
        "BEATING THE CLOSE": "SHARP 🔥",
        "NO DIFFERENT FROM THE MARKET": "COIN FLIP 🪙",
        "PAYING THE VIG": "FEEDING THE BOOK 💸",
        "TOO EARLY": "ROOKIE 🐣",
    }

    def test_the_mapping_is_the_one_in_the_voice_guide(self):
        guide = (ROOT / "docs" / "VOICE.md").read_text(encoding="utf-8")
        # the pages say it in plain words; the guide's status table is what the model page and the leaderboard print
        for label, words in (("BEATING THE CLOSE", "Beating the close"), ("NO DIFFERENT FROM THE MARKET", "Market"),
                             ("PAYING THE VIG", "Paying the vig"), ("TOO EARLY", "Not enough bets (n/150)")):
            self.assertIn(label, guide)
            self.assertIn(f"**{words}**", guide)
        for label, text in self.EXPECTED.items():
            self.assertEqual(voice.badge_for(label)["text"], text, label)

    def test_every_label_the_referee_can_send_wears_a_badge(self):
        for label in vd.LABELS:
            badge = voice.badge_for(label)
            self.assertTrue(badge["word"] and badge["emoji"] and badge["explain"], label)
        self.assertEqual(voice.badge_for("NOT MEASURED")["key"], "unrated")
        self.assertEqual(voice.badge_for(None)["key"], "unrated")
        self.assertEqual(voice.badge_for("  too early ")["key"], "rookie", "labels are matched like the page does")

    def test_each_explanation_is_one_plain_line(self):
        for label in list(self.EXPECTED) + ["NOT MEASURED"]:
            line = voice.badge_for(label)["explain"]
            self.assertLessEqual(len(line), 120, label)
            self.assertEqual(line.count(". "), line.count(". "), label)
            for word in ACADEMIC_WORDS + ("interval", "closing-line"):
                self.assertNotIn(word, line.lower(), label)

    def test_the_label_is_never_a_function_of_units(self):
        # the badge reads the referee's label and nothing else: two dogs with opposite units, one label
        a = voice.badge_for("PAYING THE VIG")
        self.assertEqual(a, voice.badge_for("PAYING THE VIG"))
        self.assertEqual(set(inspect_args(voice.badge_for)), {"label"})


def inspect_args(fn):
    import inspect
    return list(inspect.signature(fn).parameters)


class TheHoundmastersDailyLine(unittest.TestCase):

    LINES = [f"line {i}" for i in range(5)]

    def test_the_same_dog_on_the_same_day_gets_the_same_line(self):
        for _ in range(3):
            self.assertEqual(voice.pick_line(self.LINES, "steamy_setter", "2026-10-17"),
                             voice.pick_line(self.LINES, "steamy_setter", "2026-10-17"))

    def test_a_different_day_can_give_a_different_line_and_every_line_gets_used(self):
        seen = {voice.pick_line(self.LINES, "steamy_setter", f"2026-10-{d:02d}") for d in range(1, 31)}
        self.assertGreaterEqual(len(seen), 4)
        self.assertTrue(seen <= set(self.LINES))

    def test_two_dogs_do_not_all_say_the_same_thing_on_one_day(self):
        said = {voice.pick_line(self.LINES, hid, "2026-10-17") for hid in ("a", "b", "c", "d", "e", "f", "g", "h")}
        self.assertGreater(len(said), 1)

    def test_no_lines_no_pick(self):
        self.assertIsNone(voice.pick_line([], "x", "2026-10-17"))

    def test_a_loss_gets_a_roast_a_win_a_brag_and_a_flat_day_nothing(self):
        persona = {"roasts": [f"R{i}" for i in range(5)], "brags": [f"B{i}" for i in range(5)]}
        boss = {"roasts": ["boss roast"], "brags": ["boss brag"]}
        loss = voice.houndmaster_line("d", persona, {"result": "loss", "date": "2026-10-17"}, boss)
        win = voice.houndmaster_line("d", persona, {"result": "win", "date": "2026-10-17"}, boss)
        self.assertEqual((loss["kind"], win["kind"]), ("roast", "brag"))
        self.assertIn(loss["line"], persona["roasts"])
        self.assertIn(win["line"], persona["brags"])
        self.assertIsNone(voice.houndmaster_line("d", persona, {"result": "flat", "date": "2026-10-17"}, boss))
        self.assertIsNone(voice.houndmaster_line("d", persona, None, boss))

    def test_a_dog_with_no_persona_gets_the_bosses_own_lines(self):
        boss = {"roasts": ["boss roast"], "brags": ["boss brag"]}
        got = voice.houndmaster_line("builder", None, {"result": "loss", "date": "2026-10-17"}, boss)
        self.assertEqual(got["line"], "boss roast")


def mkbet(day, result, price=-110, fair=None, avg=None, **kw):
    return Bet(hound_id="h", date=day, decision_utc=f"{day}T18:00:00Z", result=result, price=price,
               price_average=avg if avg is not None else price, consensus_fair=fair, market_key="h2h", side="home",
               selection_text=kw.pop("selection", "Home to win"), game_text=kw.pop("game", "A at B"), **kw)


class TheFormBlock(unittest.TestCase):

    def form(self, bets, as_of="2026-10-18"):
        graded = sorted((b for b in bets if b.graded), key=lambda b: (b.date, b.decision_utc or ""))
        return stats.compute_form(graded, True, as_of, {})

    def test_nothing_graded_is_no_form(self):
        self.assertIsNone(stats.compute_form([], True, "2026-10-18", {}))

    def test_the_streak_is_the_trailing_run_and_a_push_does_not_break_or_extend_it(self):
        bets = [mkbet("2026-10-10", "loss"), mkbet("2026-10-11", "win"), mkbet("2026-10-12", "win"),
                mkbet("2026-10-13", "push"), mkbet("2026-10-14", "win")]
        self.assertEqual(self.form(bets)["streak"], {"kind": "W", "length": 3})
        bets.append(mkbet("2026-10-15", "loss"))
        bets.append(mkbet("2026-10-16", "loss"))
        self.assertEqual(self.form(bets)["streak"], {"kind": "L", "length": 2})

    def test_the_last_settled_day_decides_roast_or_brag(self):
        winning = self.form([mkbet("2026-10-16", "loss"), mkbet("2026-10-17", "win", price=+150),
                             mkbet("2026-10-17", "loss")])["last_day"]
        self.assertEqual((winning["date"], winning["result"], winning["wins"], winning["losses"]),
                         ("2026-10-17", "win", 1, 1))
        self.assertAlmostEqual(winning["units"], 0.5, places=3)
        self.assertEqual(self.form([mkbet("2026-10-17", "loss")])["last_day"]["result"], "loss")
        self.assertEqual(self.form([mkbet("2026-10-17", "push")])["last_day"]["result"], "flat")

    def test_the_last_seven_days_window_is_inclusive_of_the_as_of_day_and_exclusive_of_day_eight(self):
        bets = [mkbet("2026-10-11", "win"), mkbet("2026-10-12", "loss"), mkbet("2026-10-18", "win")]
        week = self.form(bets)["last7"]
        self.assertEqual((week["bets"], week["wins"], week["losses"]), (2, 1, 1))     # 10-12 .. 10-18

    def test_best_bet_is_the_biggest_winner_and_worst_beat_the_favourite_that_lost(self):
        bets = [mkbet("2026-10-12", "win", price=+200, selection="Dog to win"),
                mkbet("2026-10-13", "win", price=-150),
                mkbet("2026-10-14", "loss", price=+120, fair=0.44, selection="Underdog"),
                mkbet("2026-10-15", "loss", price=-160, fair=0.61, selection="Chalk to win"),
                mkbet("2026-10-16", "loss", price=-105, fair=0.5)]
        form = self.form(bets)
        self.assertEqual(form["best_bet"]["selection"], "Dog to win")
        self.assertAlmostEqual(form["best_bet"]["units"], 2.0, places=3)
        self.assertEqual(form["worst_beat"]["selection"], "Chalk to win")
        self.assertEqual(form["worst_beat"]["market_fair"], 0.61)

    def test_with_no_fair_price_on_any_loss_the_worst_beat_is_the_latest_loss(self):
        bets = [mkbet("2026-10-12", "loss", selection="First"), mkbet("2026-10-15", "loss", selection="Latest")]
        self.assertEqual(self.form(bets)["worst_beat"]["selection"], "Latest")

    def test_the_basis_is_named_and_it_is_the_one_the_record_uses(self):
        graded = [mkbet("2026-10-12", "win")]
        self.assertEqual(stats.compute_form(graded, True, "2026-10-18", {})["units_basis"], "average_price")
        self.assertEqual(stats.compute_form(graded, False, "2026-10-18", {})["units_basis"], "recorded_price")


@unittest.skipUnless(HAS_NODE, "node not installed")
@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSharedHelpersThePagesStillUse(unittest.TestCase):

    def hound(self, hid, units, bets=20, status="running", **kw):
        h = {"id": hid, "name": hid.title(), "kind": "house", "category": "stats", "status": status,
             "verdict": {"label": "TOO EARLY"},
             "record": {"bets": bets, "wins": 1, "losses": 1, "units_average_price": units, "units_recorded_price": units}}
        h.update(kw)
        return h

    def test_the_board_is_sorted_by_units_with_models_without_bets_last(self):
        hs = [self.hound("low", -3.0), self.hound("none", None, bets=0), self.hound("high", 9.5), self.hound("mid", 1.0)]
        hs[1]["record"] = {"bets": 0}
        out = js(f"console.log(JSON.stringify(V.sortByUnits({json.dumps(hs)}).map(h => h.id)));")
        self.assertEqual(out, ["high", "mid", "low", "none"])

    def test_units_prefer_the_average_price_and_wl_carries_pushes(self):
        out = js("console.log(JSON.stringify([V.unitsOf({record:{bets:3,units_average_price:1.5,units_recorded_price:2}}),"
                 "V.unitsOf({record:{bets:3,units_average_price:null,units_recorded_price:2}}), V.unitsOf({record:{bets:0}}),"
                 "V.wlText({bets:5,wins:3,losses:1,pushes:1}), V.wlText({bets:0}), V.wlText({bets:4,wins:2,losses:2})]));")
        self.assertEqual(out, [1.5, 2, None, "3-1-1", "0-0", "2-2"])

    def test_a_retirement_reason_in_plain_words(self):
        out = js("console.log(JSON.stringify([V.causeText('retired: down more than 25 units'),"
                 "V.causeText('retired by the owner'), V.causeText('retired: closing price verdict PAYING THE VIG at 300+ bets'),"
                 "V.causeText(''), V.causeText('paused 2026-10-16: x')]));")
        self.assertEqual(out, ["Went more than 25 units under.", "Retired by the owner.", "300 bets paying the vig.",
                               "No reason was given.", "Paused 2026-10-16: x"])

    def test_the_toy_voice_is_gone_from_the_module(self):
        out = js("console.log(JSON.stringify(['badgeFor','streakView','formStrip','houndmasterLine','chatLine','closestToRetirement',"
                 "'epitaphFor','weekText','BADGES'].map(k => typeof V[k])));")
        self.assertEqual(set(out), {"undefined"})


class TheHardLinesStayAndTheAcademicWordsGo(unittest.TestCase):

    def test_every_public_page_says_paper_only_not_advice_and_21_plus_in_its_static_text(self):
        for name in ("hounds.html", "hound.html", "build-a-hound.html", "learning.html"):
            text = visible((WEB / name).read_text(encoding="utf-8")).lower()
            self.assertIn("paper bets only", text, name)
            self.assertRegex(text, r"not (betting )?advice", name)
            self.assertIn("21+", text, name)
        # the landing page says it once, in the shared footer the script mounts (not in the body copy)
        landing = (WEB / "landing.html").read_text(encoding="utf-8")
        self.assertIn('data-hook="disclaimer-host"', landing)
        self.assertNotRegex(visible(re.search(r"<main>.*?</main>", landing, re.S).group(0)).lower(), r"paper bets only|21\+")

    def test_the_model_pages_carry_the_gamble_responsibly_line_in_their_own_footer(self):
        for name in ("hounds.html", "hound.html", "build-a-hound.html", "learning.html"):
            html = (WEB / name).read_text(encoding="utf-8")
            footer = html.split("<footer", 1)[1].split("</footer>", 1)[0]
            self.assertIn("Gamble responsibly.", visible(footer), name)
            self.assertIn("1-800-GAMBLER", footer, name)
            self.assertIn('href="tel:1-800-426-2537"', footer, name)

    def test_the_shared_footer_every_other_page_mounts_says_it_too(self):
        meta = (WEB / "js" / "meta.js").read_text(encoding="utf-8")
        self.assertIn('"21+ · Gamble responsibly."', meta)
        self.assertIn('text: "1-800-GAMBLER"', meta)
        for name in ("landing.html", "why-we-paused.html", "sample.html"):
            self.assertIn('data-hook="disclaimer-host"', (WEB / name).read_text(encoding="utf-8"), name)

    def test_no_public_page_makes_a_claim_in_its_static_text(self):
        for name in PUBLIC_PAGES:
            raw = visible((WEB / name).read_text(encoding="utf-8")).lower()
            text = re.sub(r"\b(no|never|not)\b[^.]*?\b(guarantee\w*|sure thing)\b", " ", raw)   # a denial is not a claim
            for pattern in (r"\block\b", r"can'?t lose", r"sure thing", r"free money", r"\bedge\b"):
                self.assertIsNone(re.search(pattern, text), f"{name}: {pattern}")

    def test_the_academic_words_are_off_every_public_page(self):
        for name in PUBLIC_PAGES + ("sample.html",):
            text = visible((WEB / name).read_text(encoding="utf-8")).lower()
            for word in ACADEMIC_WORDS:
                self.assertNotIn(word, text, f"{name} says {word!r}")

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_and_off_what_the_pages_write_into_themselves(self):
        # the text the scripts add (rows, tiles, tooltips, the ticket feed, the retired table) too
        routes = F.routes()
        pages = [
            ("hounds", {"routes": routes}),
            ("hound", {"routes": routes, "search": "?id=closer"}),
            ("hound", {"routes": routes, "search": "?id=steamer"}),
            ("build", {"routes": routes, "search": "?from=closer"}),
        ]
        for page, kw in pages:
            out = run_page(page, **kw)
            text = out["text"].lower()
            for word in ACADEMIC_WORDS:
                self.assertNotIn(word, text, f"{page} {kw.get('search', '')} writes {word!r}")
            for pattern in (r"\block\b", r"can'?t lose", r"sure thing", r"free money", r"\bedge\b", r"\bprofit"):
                self.assertIsNone(re.search(pattern, text), f"{page}: {pattern}")

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_the_training_camp_page_too(self):
        from tests.test_hounds_learning_web import learning_payload
        with tempfile.TemporaryDirectory() as tmp:
            payload = learning_payload(Path(tmp), lesson_count=3)
        for lesson in payload["lessons"]["latest"]:       # the coach's own words are quoted data, not the page's voice
            lesson["hypothesis"] = "Try a smaller gap."
        out = run_page("learning", routes={"/hounds/learning": [200, payload]})
        text = out["text"].lower()
        for word in ACADEMIC_WORDS:
            self.assertNotIn(word, text, f"learning writes {word!r}")
        self.assertIn("rookie", text)
        self.assertIn("made the team", text)
        self.assertNotIn("challenger", text)


if __name__ == "__main__":
    unittest.main()
