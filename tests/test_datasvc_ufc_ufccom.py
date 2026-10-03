"""UFC.com career profiles: slugs to try, the page parser, and the fetcher that refuses the wrong person.

No network. The fetcher is the real `PoliteFetcher` with an opener that serves saved pages by URL (a URL
nobody registered fails the test instead of going out). The expected numbers for each saved page were read
off the page's own markup, not copied from the parser's output.
"""
import email.message
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from src.datasvc import http
from src.datasvc.ufc import espn_urls, fighters, ufccom
from src.datasvc.ufc.store import UfcStore

HERE = Path(__file__).resolve().parent
UFC_PAGES = HERE / "fixtures" / "ufccom"
ESPN = HERE / "fixtures" / "espn_mma"
NOW = "2026-10-03T18:00:00Z"

# The fields a parse returns, written out here independently of the module.
IDENTITY = ("page_name", "page_nickname", "page_division", "page_status", "ufc_slug", "record_text", "record")
FIGURES = (
    "wins_ko", "wins_sub", "wins_dec", "first_round_finishes", "title_defenses",
    "sig_str_landed_per_min", "sig_str_absorbed_per_min", "sig_str_accuracy_pct", "sig_str_defense_pct",
    "sig_str_landed", "sig_str_attempted",
    "takedown_avg_per_15", "takedown_accuracy_pct", "takedown_defense_pct", "takedowns_landed", "takedowns_attempted",
    "submission_avg_per_15", "knockdown_avg_per_15", "avg_fight_time_s",
    "sig_str_standing", "sig_str_standing_pct", "sig_str_clinch", "sig_str_clinch_pct",
    "sig_str_ground", "sig_str_ground_pct",
    "sig_str_head", "sig_str_head_pct", "sig_str_body", "sig_str_body_pct", "sig_str_leg", "sig_str_leg_pct",
)
BIO = ("place_of_birth", "trains_at", "fighting_style", "octagon_debut",
       "ufc_height_in", "ufc_weight_lb", "ufc_reach_in", "ufc_leg_reach_in")
UFC_ONLY = tuple(f for f in FIGURES if f not in ("wins_ko", "wins_sub", "wins_dec", "first_round_finishes",
                                                 "title_defenses"))


def page_text(name):
    return (UFC_PAGES / name).read_text(encoding="utf-8")


def page_bytes(name):
    return (UFC_PAGES / name).read_bytes()


def espn_json(name):
    return json.loads((ESPN / name).read_text(encoding="utf-8"))


def expected(**given):
    """A full parse result with everything null/empty except what is given (notes excluded)."""
    base = {name: None for name in IDENTITY + FIGURES + BIO}
    base["other_figures"] = {}
    unknown = set(given) - set(base)
    assert not unknown, unknown
    base.update(given)
    return base


def parsed(name):
    profile = ufccom.parse_profile(page_text(name))
    notes = profile.pop("notes")
    return profile, notes


# What each saved page shows, read from its markup.
PAGES = {
    "athlete_ismail-naurdiev.html": expected(
        page_name="Ismail Naurdiev", page_nickname="Berzdog", page_division="Middleweight", page_status="Active",
        ufc_slug="ismail-naurdiev", record_text="25-8-0 (W-L-D)", record={"wins": 25, "losses": 8, "draws": 0},
        wins_ko=13, wins_sub=6, wins_dec=6, first_round_finishes=16,
        sig_str_landed_per_min=3.66, sig_str_absorbed_per_min=1.75, sig_str_accuracy_pct=53, sig_str_defense_pct=65,
        sig_str_landed=335, sig_str_attempted=634,
        takedown_avg_per_15=1.48, takedown_accuracy_pct=None, takedown_defense_pct=73,        # page: 0%, landed blank
        takedowns_landed=None, takedowns_attempted=22,
        submission_avg_per_15=0.16, knockdown_avg_per_15=0.16, avg_fight_time_s=784,          # 13:04
        sig_str_standing=266, sig_str_standing_pct=79, sig_str_clinch=36, sig_str_clinch_pct=11,
        sig_str_ground=33, sig_str_ground_pct=10,
        sig_str_head=183, sig_str_head_pct=55, sig_str_body=88, sig_str_body_pct=26, sig_str_leg=64, sig_str_leg_pct=19,
        place_of_birth="Rabat, Morocco", trains_at="Team Naurdiev", fighting_style="Wrestling",
        octagon_debut="2019-02-23", ufc_height_in=72.0, ufc_weight_lb=185.0, ufc_reach_in=74.0, ufc_leg_reach_in=40.5),
    "w2_athlete_jose-aldo.html": expected(                       # retired, no nickname
        page_name="José Aldo", page_nickname=None, page_division="Featherweight", page_status="Retired",
        ufc_slug="jose-aldo", record_text="32-10-0 (W-L-D)", record={"wins": 32, "losses": 10, "draws": 0},
        wins_ko=17, wins_sub=1, wins_dec=14, first_round_finishes=12,
        sig_str_landed_per_min=3.65, sig_str_absorbed_per_min=3.81, sig_str_accuracy_pct=46, sig_str_defense_pct=60,
        sig_str_landed=1617, sig_str_attempted=3492,
        takedown_avg_per_15=0.47, takedown_accuracy_pct=44, takedown_defense_pct=93,
        takedowns_landed=12, takedowns_attempted=27,
        submission_avg_per_15=0.14, knockdown_avg_per_15=0.41, avg_fight_time_s=857,          # 14:17
        sig_str_standing=1409, sig_str_standing_pct=87, sig_str_clinch=60, sig_str_clinch_pct=4,
        sig_str_ground=148, sig_str_ground_pct=9,
        sig_str_head=1064, sig_str_head_pct=66, sig_str_body=322, sig_str_body_pct=20,
        sig_str_leg=231, sig_str_leg_pct=14,
        place_of_birth="Manaus, Brazil", trains_at="Nova União", fighting_style="Jiu-Jitsu",
        octagon_debut="2011-04-30", ufc_height_in=67.0, ufc_weight_lb=143.0, ufc_reach_in=70.0, ufc_leg_reach_in=40.0),
    "w2_athlete_lucas-armand.html": expected(                    # no UFC fight yet: figures are printed placeholders
        page_name="Lucas Armand", page_nickname="Do or Die", page_division="Heavyweight", page_status="Active",
        ufc_slug="lucas-armand", record_text="6-0-0 (W-L-D)", record={"wins": 6, "losses": 0, "draws": 0},
        wins_ko=5, wins_sub=0, wins_dec=1, first_round_finishes=2,      # sub wins from the method block: the hero omits it
        place_of_birth="Big Rapids, United States", trains_at="Murcielago MMA", fighting_style="Freestyle",
        octagon_debut="2026-10-03", ufc_height_in=74.5, ufc_weight_lb=265.0, ufc_reach_in=78.5, ufc_leg_reach_in=44.0),
    "w2_athlete_raul-rosas-jr.html": expected(                   # suffix in the name, a ranking tag
        page_name="Raul Rosas Jr.", page_nickname="El Nino Problema", page_division="Bantamweight",
        page_status="Active", ufc_slug="raul-rosas-jr", record_text="13-1-0 (W-L-D)",
        record={"wins": 13, "losses": 1, "draws": 0},
        wins_ko=3, wins_sub=6, wins_dec=4, first_round_finishes=6,
        sig_str_landed_per_min=2.12, sig_str_absorbed_per_min=2.17, sig_str_accuracy_pct=44, sig_str_defense_pct=48,
        sig_str_landed=228, sig_str_attempted=522,
        takedown_avg_per_15=5.02, takedown_accuracy_pct=3, takedown_defense_pct=54,
        takedowns_landed=2, takedowns_attempted=67,
        submission_avg_per_15=0.7, knockdown_avg_per_15=0.14, avg_fight_time_s=718,           # 11:58
        sig_str_standing=165, sig_str_standing_pct=72, sig_str_clinch=18, sig_str_clinch_pct=8,
        sig_str_ground=45, sig_str_ground_pct=20,
        sig_str_head=165, sig_str_head_pct=72, sig_str_body=27, sig_str_body_pct=12, sig_str_leg=36, sig_str_leg_pct=16,
        place_of_birth="Clovis, United States", trains_at="Rosas Brothers MMA", fighting_style="Freestyle",
        octagon_debut="2022-12-10", ufc_height_in=69.0, ufc_weight_lb=135.0, ufc_reach_in=67.0, ufc_leg_reach_in=40.0),
    "w2_athlete_anderson-silva.html": expected(                  # "Title Defenses" instead of first-round finishes; thin bio
        page_name="Anderson Silva", page_nickname="The Spider", page_division="Middleweight", page_status=None,
        ufc_slug="anderson-silva", record_text="34-11-0 (W-L-D)", record={"wins": 34, "losses": 11, "draws": 0},
        wins_ko=22, wins_sub=4, wins_dec=8, first_round_finishes=None, title_defenses=10,
        sig_str_landed_per_min=3.05, sig_str_absorbed_per_min=2.05, sig_str_accuracy_pct=62, sig_str_defense_pct=61,
        sig_str_landed=1282, sig_str_attempted=2084,
        takedown_avg_per_15=0.5, takedown_accuracy_pct=17, takedown_defense_pct=69,
        takedowns_landed=3, takedowns_attempted=18,
        submission_avg_per_15=0.79, knockdown_avg_per_15=0.86, avg_fight_time_s=615,          # 10:15
        sig_str_standing=839, sig_str_standing_pct=65, sig_str_clinch=202, sig_str_clinch_pct=16,
        sig_str_ground=241, sig_str_ground_pct=19,
        sig_str_head=756, sig_str_head_pct=59, sig_str_body=241, sig_str_body_pct=19,
        sig_str_leg=285, sig_str_leg_pct=22,
        place_of_birth="State of Sao Paulo, Brazil", trains_at=None, fighting_style=None,
        octagon_debut="2006-06-28", ufc_height_in=74.0, ufc_weight_lb=184.0, ufc_reach_in=77.0, ufc_leg_reach_in=42.5),
    "w2_athlete_bruno-silva.html": expected(                     # the flyweight "Bulldog"
        page_name="Bruno Silva", page_nickname="Bulldog", page_division="Flyweight", page_status="Active",
        ufc_slug="bruno-silva", record_text="15-9-2 (W-L-D)", record={"wins": 15, "losses": 9, "draws": 2},
        wins_ko=6, wins_sub=5, wins_dec=4, first_round_finishes=4,
        sig_str_landed_per_min=3.95, sig_str_absorbed_per_min=4.72, sig_str_accuracy_pct=51, sig_str_defense_pct=51,
        sig_str_landed=489, sig_str_attempted=952,
        takedown_avg_per_15=1.94, takedown_accuracy_pct=3, takedown_defense_pct=72,
        takedowns_landed=2, takedowns_attempted=66,
        submission_avg_per_15=0.24, knockdown_avg_per_15=0.85, avg_fight_time_s=619,          # 10:19
        sig_str_standing=419, sig_str_standing_pct=86, sig_str_clinch=28, sig_str_clinch_pct=6,
        sig_str_ground=42, sig_str_ground_pct=9,
        sig_str_head=289, sig_str_head_pct=59, sig_str_body=111, sig_str_body_pct=23, sig_str_leg=89, sig_str_leg_pct=18,
        place_of_birth="Piracicaba, Brazil", trains_at="Fight Ready", fighting_style="Grappler",
        octagon_debut="2019-09-07", ufc_height_in=64.0, ufc_weight_lb=125.5, ufc_reach_in=65.0, ufc_leg_reach_in=35.0),
    "w2_athlete_isaac-vallie-flagg.html": expected(              # no hero stats, no nickname: wins only from the method block
        page_name="Isaac Vallie-Flagg", page_nickname=None, page_division="Lightweight", page_status="Not Fighting",
        ufc_slug="isaac-vallie-flagg", record_text="14-5-1 (W-L-D)", record={"wins": 14, "losses": 5, "draws": 1},
        wins_ko=6, wins_sub=2, wins_dec=6,
        sig_str_landed_per_min=5.56, sig_str_absorbed_per_min=5.6, sig_str_accuracy_pct=48, sig_str_defense_pct=45,
        sig_str_landed=417, sig_str_attempted=871,
        takedown_avg_per_15=0.2, takedown_accuracy_pct=None, takedown_defense_pct=59,        # page: 0%, landed blank
        takedowns_landed=None, takedowns_attempted=8,
        submission_avg_per_15=0.0, knockdown_avg_per_15=0.0, avg_fight_time_s=900,           # real zeros; 15:00
        sig_str_standing=282, sig_str_standing_pct=68, sig_str_clinch=128, sig_str_clinch_pct=31,
        sig_str_ground=7, sig_str_ground_pct=2,
        sig_str_head=256, sig_str_head_pct=61, sig_str_body=92, sig_str_body_pct=22, sig_str_leg=69, sig_str_leg_pct=17,
        place_of_birth="United States", octagon_debut="2012-05-20",                          # "May. 20, 2012"
        ufc_height_in=68.0, ufc_weight_lb=156.0, ufc_reach_in=70.0),                         # no leg reach on the page
    "w2_athlete_bruno-silva-blindado.html": expected(            # the middleweight "Blindado", reached as /bruno-silva-0
        page_name="Bruno Silva", page_nickname="Blindado", page_division="Middleweight", page_status="Not Fighting",
        ufc_slug="bruno-silva-blindado", record_text="23-13-0 (W-L-D)",
        record={"wins": 23, "losses": 13, "draws": 0},
        wins_ko=20, wins_sub=0, wins_dec=3, first_round_finishes=14,
        sig_str_landed_per_min=3.86, sig_str_absorbed_per_min=5.35, sig_str_accuracy_pct=48, sig_str_defense_pct=42,
        sig_str_landed=376, sig_str_attempted=783,
        takedown_avg_per_15=0.77, takedown_accuracy_pct=9, takedown_defense_pct=74,
        takedowns_landed=2, takedowns_attempted=22,
        submission_avg_per_15=0.0, knockdown_avg_per_15=0.31, avg_fight_time_s=531,           # a real 0.00; 08:51
        sig_str_standing=274, sig_str_standing_pct=73, sig_str_clinch=44, sig_str_clinch_pct=12,
        sig_str_ground=58, sig_str_ground_pct=15,
        sig_str_head=284, sig_str_head_pct=76, sig_str_body=58, sig_str_body_pct=15, sig_str_leg=34, sig_str_leg_pct=9,
        place_of_birth="Brazil", trains_at="Evolucao Thai - Curitiba", fighting_style="Striker",
        octagon_debut="2021-06-19", ufc_height_in=72.0, ufc_weight_lb=187.0, ufc_reach_in=74.0, ufc_leg_reach_in=42.0),
}


# What UFC.com serves for a slug it does not have: its search page, HTTP 200 (captured live).
NON_ATHLETE_PAGES = {"w2_search_results_unknown_slug.html"}
# Pages whose takedown block prints "0%" over a blank landed count.
BLANK_TAKEDOWN_PAGES = {"athlete_ismail-naurdiev.html", "w2_athlete_isaac-vallie-flagg.html"}


class ParseSavedPages(unittest.TestCase):
    def test_every_saved_page_parses_to_exactly_the_numbers_it_shows(self):
        saved = {p.name for p in UFC_PAGES.glob("*.html")} - NON_ATHLETE_PAGES
        self.assertEqual(saved, set(PAGES), "a saved page has no expected values (or the reverse)")
        for name, want in PAGES.items():
            with self.subTest(page=name):
                profile, _ = parsed(name)
                self.assertEqual(profile, want)

    def test_the_result_has_the_documented_keys_in_order(self):
        profile = ufccom.parse_profile(page_text("athlete_ismail-naurdiev.html"))
        self.assertEqual(tuple(profile), IDENTITY + FIGURES + BIO + ("other_figures", "notes"))
        self.assertEqual(ufccom.PROFILE_FIELDS, tuple(profile))

    def test_a_clean_page_has_no_notes_and_the_two_placeholder_pages_say_so(self):
        for name in PAGES:
            _, notes = parsed(name)
            if name in BLANK_TAKEDOWN_PAGES:
                self.assertEqual(len(notes), 1)
                self.assertIn("takedown_accuracy_pct", notes[0])
                self.assertIn("takedowns_landed", notes[0])
            elif name == "w2_athlete_lucas-armand.html":
                self.assertEqual(len(notes), 1)
                self.assertIn("no UFC fight data", notes[0])
            else:
                self.assertEqual(notes, [], name)

    def test_every_page_adds_up_the_way_a_correct_parse_must(self):
        # Wrong label-to-field mapping would break these sums, whatever the parser believes it read.
        for name in PAGES:
            profile, _ = parsed(name)
            if profile["sig_str_landed"] is None:
                continue
            landed = profile["sig_str_landed"]
            self.assertEqual(profile["sig_str_standing"] + profile["sig_str_clinch"] + profile["sig_str_ground"], landed, name)
            self.assertEqual(profile["sig_str_head"] + profile["sig_str_body"] + profile["sig_str_leg"], landed, name)
            self.assertAlmostEqual(100.0 * landed / profile["sig_str_attempted"], profile["sig_str_accuracy_pct"], delta=1, msg=name)
            self.assertEqual(profile["wins_ko"] + profile["wins_dec"] + profile["wins_sub"], profile["record"]["wins"], name)

    def test_the_canonical_slug_is_the_real_one_even_for_an_alias_page(self):
        # /athlete/bruno-silva-0 serves the page whose canonical link is bruno-silva-blindado.
        profile, _ = parsed("w2_athlete_bruno-silva-blindado.html")
        self.assertEqual(profile["ufc_slug"], "bruno-silva-blindado")

    def test_a_printed_zero_is_kept_when_the_fighter_has_ufc_data_and_dropped_when_not(self):
        real, _ = parsed("w2_athlete_bruno-silva-blindado.html")
        self.assertEqual((real["submission_avg_per_15"], real["wins_sub"]), (0.0, 0))
        none, _ = parsed("w2_athlete_lucas-armand.html")
        for name in UFC_ONLY:
            self.assertIsNone(none[name], name)
        self.assertEqual((none["wins_ko"], none["wins_sub"], none["wins_dec"]), (5, 0, 1))    # career wins are real

    def test_the_search_page_UFC_serves_for_a_missing_athlete_parses_to_nothing(self):
        for name in NON_ATHLETE_PAGES:
            profile = ufccom.parse_profile(page_text(name))
            self.assertIsNone(profile["page_name"], name)
            self.assertIsNone(profile["ufc_slug"], name)            # its canonical link is /search, not an athlete
            self.assertIsNone(profile["record"], name)
            for field in FIGURES + BIO:
                self.assertIsNone(profile[field], (name, field))

    def test_bytes_and_text_give_the_same_parse_and_none_is_an_empty_page(self):
        text = page_text("w2_athlete_raul-rosas-jr.html")
        self.assertEqual(ufccom.parse_profile(text), ufccom.parse_profile(text.encode("utf-8")))
        empty = ufccom.parse_profile(None)
        self.assertIsNone(empty["page_name"])


def athlete_page(*, name="Test Fighter", record="10-2-0 (W-L-D)", head="", stats="", bio=""):
    """A minimal athlete page: hero, a #athlete-stats section and a bio, each as raw markup."""
    return (f'<html><head>{head}</head><body>'
            f'<h1 class="hero-profile__name">{name}</h1>'
            f'<p class="hero-profile__division-body">{record}</p>'
            f'<div id="athlete-stats">{stats}</div>'
            f'<div class="c-bio c-bio--athlete">{bio}</div></body></html>')


def compare(label, number, suffix=""):
    num = f'<div class="c-stat-compare__number">{number}</div>' if number is not None else ""
    suf = f'<div class="c-stat-compare__label-suffix">{suffix}</div>' if suffix else ""
    return (f'<div class="c-stat-compare__group">{num}<div class="c-stat-compare__label">{label}</div>{suf}</div>')


def bar(title, rows):
    groups = "".join(f'<div class="c-stat-3bar__group"><div class="c-stat-3bar__label">{k} </div>'
                     f'<div class="c-stat-3bar__value">{v}</div></div>' for k, v in rows)
    return f'<div class="c-stat-3bar"><h2 class="c-stat-3bar__title">{title}</h2>{groups}</div>'


def accuracy(title, pct, rows):
    dls = "".join(f'<dl class="c-overlap__stats"><dt>{k}</dt><dd>{v}</dd></dl>' for k, v in rows)
    return (f'<div class="overlap-athlete-content"><svg><title>{title} {pct}</title>'
            f'<text class="e-chart-circle__percent">{pct}</text></svg><h2>{title}</h2>{dls}</div>')


def bio_field(label, text):
    return f'<div class="c-bio__field"><div class="c-bio__label">{label}</div><div class="c-bio__text">{text}</div></div>'


class ParseVariants(unittest.TestCase):
    def test_a_page_that_is_not_an_athlete_page_parses_to_nothing_without_raising(self):
        profile = ufccom.parse_profile("<html><head><title>Not found</title></head><body><h1>Page not found</h1></body></html>")
        self.assertIsNone(profile["page_name"])
        self.assertIsNone(profile["record"])
        for name in FIGURES + BIO:
            self.assertIsNone(profile[name], name)
        self.assertEqual(profile["other_figures"], {})
        self.assertTrue(any("no UFC fight data" in n for n in profile["notes"]))

    def test_an_athlete_page_with_no_known_figure_blocks_says_so_but_blank_blocks_do_not(self):
        renamed = ufccom.parse_profile(athlete_page(stats='<div class="renamed-block"><span>Sig. Str. Landed 3.66</span></div>'))
        self.assertEqual(renamed["page_name"], "Test Fighter")
        self.assertTrue(any("layout" in n for n in renamed["notes"]), renamed["notes"])
        blank = ufccom.parse_profile(athlete_page(stats=compare("Sig. Str. Landed", None, "Per Min")))
        self.assertFalse(any("layout" in n for n in blank["notes"]), blank["notes"])
        self.assertFalse(any("layout" in n for n in ufccom.parse_profile("<html></html>")["notes"]))

    def test_the_division_loses_only_the_word_division(self):
        for text, want in (("Women's Strawweight Division", "Women's Strawweight"), ("Catch Weight", "Catch Weight"),
                           ("Light Heavyweight Division", "Light Heavyweight")):
            html = f'<html><body><p class="hero-profile__division-title">{text}</p></body></html>'
            self.assertEqual(ufccom.parse_profile(html)["page_division"], want, text)

    def test_text_inside_scripts_is_never_read_as_the_page(self):
        html = ('<html><body><h1 class="hero-profile__name">Real Name</h1>'
                '<script>document.write(\'<h1 class="hero-profile__name">Evil Name</h1>\')</script>'
                '<style>.x{content:"Wins by Knockout 99"}</style></body></html>')
        self.assertEqual(ufccom.parse_profile(html)["page_name"], "Real Name")

    def test_an_unknown_label_and_a_changed_unit_go_to_other_figures_never_to_a_field(self):
        stats = (compare("Sig. Str. Absorbed", "2.5", "Per Min") + compare("Clinch Strikes", "4.5", "Per Min")
                 + compare("Sig. Str. Landed", "3.1", "Per 15 Min")          # the unit changed: not sig_str_landed_per_min
                 + compare("Average fight time", "10:00"))
        profile = ufccom.parse_profile(athlete_page(stats=stats))
        self.assertEqual(profile["sig_str_absorbed_per_min"], 2.5)
        self.assertIsNone(profile["sig_str_landed_per_min"])
        self.assertEqual(profile["avg_fight_time_s"], 600)
        self.assertEqual(profile["other_figures"], {"Clinch Strikes Per Min": 4.5, "Sig. Str. Landed Per 15 Min": 3.1})

    def test_durations_in_minutes_and_hours(self):
        for text, seconds in (("13:04", 784), ("00:30", 30), ("1:02:15", 3735)):
            profile = ufccom.parse_profile(athlete_page(stats=compare("Average fight time", text) + compare("Knockdown Avg", "0.5")))
            self.assertEqual(profile["avg_fight_time_s"], seconds, text)
        bad = ufccom.parse_profile(athlete_page(stats=compare("Average fight time", "n/a") + compare("Knockdown Avg", "0.5")))
        self.assertIsNone(bad["avg_fight_time_s"])

    def test_all_zero_figures_are_placeholders_but_one_real_figure_makes_every_zero_real(self):
        zeros = (compare("Average fight time", "00:00") + bar("Sig. Str. By Position", [("Standing", "0 (0 %)"), ("Clinch", "0 (0 %)"), ("Ground", "0 (0 %)")]))
        profile = ufccom.parse_profile(athlete_page(stats=zeros))
        for name in UFC_ONLY:
            self.assertIsNone(profile[name], name)
        self.assertTrue(any("no UFC fight data" in n for n in profile["notes"]))
        real = (compare("Average fight time", "00:30") + bar("Sig. Str. By Position", [("Standing", "5 (100%)"), ("Clinch", "0 (0%)"), ("Ground", "0 (0%)")]))
        profile = ufccom.parse_profile(athlete_page(stats=real))
        self.assertEqual((profile["sig_str_standing"], profile["sig_str_clinch"], profile["sig_str_ground"]), (5, 0, 0))
        self.assertEqual((profile["sig_str_clinch_pct"], profile["avg_fight_time_s"]), (0, 30))

    def test_zero_percent_with_a_blank_landed_count_is_null_but_zero_of_twenty_two_is_zero(self):
        blank = accuracy("Takedown Accuracy", "0%", [("Takedowns Landed", ""), ("Takedowns Attempted", "22")])
        profile = ufccom.parse_profile(athlete_page(stats=blank + compare("Average fight time", "10:00")))
        self.assertIsNone(profile["takedown_accuracy_pct"])
        self.assertEqual((profile["takedowns_landed"], profile["takedowns_attempted"]), (None, 22))
        self.assertTrue(any("takedown_accuracy_pct" in n for n in profile["notes"]))
        honest = accuracy("Takedown Accuracy", "0%", [("Takedowns Landed", "0"), ("Takedowns Attempted", "22")])
        profile = ufccom.parse_profile(athlete_page(stats=honest + compare("Average fight time", "10:00")))
        self.assertEqual((profile["takedown_accuracy_pct"], profile["takedowns_landed"]), (0, 0))
        self.assertEqual(profile["notes"], [])

    def test_figures_outside_the_stats_section_are_ignored(self):
        real = compare("Sig. Str. Landed", "3.66", "Per Min") + compare("Average fight time", "10:00")
        decoy = (compare("Sig. Str. Landed", "99", "Per Min")
                 + bar("Sig. Str. By Position", [("Standing", "9 (90%)"), ("Clinch", "1 (10%)"), ("Ground", "0 (0%)")])
                 + accuracy("Striking accuracy", "88%", [("Sig. Strikes Landed", "88"), ("Sig. Strikes Attempted", "100")])
                 + '<svg><text id="e-stat-body_x5F__x5F_head_value">77</text></svg>')
        html = athlete_page(stats=real).replace("</body>", f"<div class='related'>{decoy}</div></body>")
        profile = ufccom.parse_profile(html)
        self.assertEqual(profile["sig_str_landed_per_min"], 3.66)
        for name in ("sig_str_standing", "sig_str_accuracy_pct", "sig_str_landed", "sig_str_head"):
            self.assertIsNone(profile[name], name)

    def test_the_circle_title_is_the_fallback_when_its_text_element_is_missing(self):
        block = ('<div class="overlap-athlete-content"><svg><title>Striking accuracy 61%</title></svg>'
                 '<h2>Striking accuracy</h2><dl class="c-overlap__stats"><dt>Sig. Strikes Landed</dt><dd>61</dd></dl>'
                 '<dl class="c-overlap__stats"><dt>Sig. Strikes Attempted</dt><dd>100</dd></dl></div>')
        profile = ufccom.parse_profile(athlete_page(stats=block + compare("Average fight time", "10:00")))
        self.assertEqual((profile["sig_str_accuracy_pct"], profile["sig_str_landed"], profile["sig_str_attempted"]), (61, 61, 100))

    def test_a_page_that_disagrees_with_itself_keeps_its_numbers_and_says_so(self):
        stats = (compare("Average fight time", "10:00")
                 + accuracy("Striking accuracy", "80%", [("Sig. Strikes Landed", "50"), ("Sig. Strikes Attempted", "100")])
                 + bar("Sig. Str. By Position", [("Standing", "20 (40%)"), ("Clinch", "10 (20%)"), ("Ground", "10 (20%)")])
                 + bar("Win by Method", [("KO/TKO", "3 (30%)"), ("DEC", "3 (30%)"), ("SUB", "3 (30%)")]))
        profile = ufccom.parse_profile(athlete_page(stats=stats, record="10-2-0 (W-L-D)"))
        self.assertEqual((profile["sig_str_accuracy_pct"], profile["sig_str_standing"]), (80, 20))
        joined = " | ".join(profile["notes"])
        for fragment in ("by position add up to 40", "sig_str_accuracy_pct is 80", "wins by method add up to 9"):
            self.assertIn(fragment, joined)

    def test_hero_counts_are_the_fallback_and_a_conflict_with_the_method_block_is_noted(self):
        hero = ('<div class="hero-profile__stat"><p class="hero-profile__stat-numb">7</p>'
                '<p class="hero-profile__stat-text">Wins by Knockout</p></div>'
                '<div class="hero-profile__stat"><p class="hero-profile__stat-numb">2</p>'
                '<p class="hero-profile__stat-text">Wins by Submission</p></div>'
                '<div class="hero-profile__stat"><p class="hero-profile__stat-numb">9</p>'
                '<p class="hero-profile__stat-text">Mystery Stat</p></div>')
        profile = ufccom.parse_profile(f'<html><body>{hero}<h1 class="hero-profile__name">A B</h1></body></html>')
        self.assertEqual((profile["wins_ko"], profile["wins_sub"], profile["wins_dec"]), (7, 2, None))
        self.assertEqual(profile["other_figures"], {"Mystery Stat": 9})
        conflict = ufccom.parse_profile(athlete_page(
            stats=hero.replace("hero-profile__", "athlete-stats__") + bar("Win by Method", [("KO/TKO", "8 (80%)"), ("DEC", "1 (10%)"), ("SUB", "1 (10%)")])))
        self.assertEqual(conflict["wins_ko"], 8)
        self.assertTrue(any("wins_ko" in n for n in conflict["notes"]))

    def test_the_record_text_is_kept_as_shown_and_the_record_read_from_its_start(self):
        for text, record in (("25-8-0 (W-L-D)", {"wins": 25, "losses": 8, "draws": 0}),
                             ("20-5-0 (1 NC)", {"wins": 20, "losses": 5, "draws": 0}),
                             ("garbage", None)):
            profile = ufccom.parse_profile(athlete_page(record=text))
            self.assertEqual((profile["record_text"], profile["record"]), (text, record))

    def test_status_comes_from_the_bio_then_from_a_hero_tag(self):
        tag = '<p class="hero-profile__tag">Retired</p>'
        self.assertEqual(ufccom.parse_profile(f'<html><body>{tag}</body></html>')["page_status"], "Retired")
        both = athlete_page(bio=bio_field("Status", "Not Fighting")).replace("<body>", f"<body>{tag}")
        self.assertEqual(ufccom.parse_profile(both)["page_status"], "Not Fighting")

    def test_bio_numbers_that_are_zero_or_blank_are_null_and_dates_are_validated(self):
        bio = (bio_field("Reach", "0.00") + bio_field("Height", "") + bio_field("Weight", "170.00")
               + bio_field("Octagon Debut", "Sept. 7, 2019") + bio_field("Leg reach", "41.50"))
        profile = ufccom.parse_profile(athlete_page(bio=bio))
        self.assertEqual((profile["ufc_reach_in"], profile["ufc_height_in"], profile["ufc_weight_lb"],
                          profile["ufc_leg_reach_in"], profile["octagon_debut"]), (None, None, 170.0, 41.5, "2019-09-07"))
        for bad in ("Feb. 31, 2019", "Smarch 3, 2019", "2019", ""):
            self.assertIsNone(ufccom.parse_profile(athlete_page(bio=bio_field("Octagon Debut", bad)))["octagon_debut"], bad)

    def test_canonical_slug_reads_only_athlete_links(self):
        link = lambda href: f'<link rel="canonical" href="{href}" />'  # noqa: E731
        for href, slug in (("https://www.ufc.com/athlete/some-name", "some-name"),
                           ("https://www.ufc.com/athlete/Some-Name/", "some-name"),
                           ("https://www.ufc.com/athlete/some-name?x=1", "some-name"),
                           ("https://www.ufc.com/events/ufc-1", None), ("", None)):
            self.assertEqual(ufccom.parse_profile(athlete_page(head=link(href)))["ufc_slug"], slug, href)
        self.assertIsNone(ufccom.parse_profile(athlete_page())["ufc_slug"])


class SlugCandidates(unittest.TestCase):
    def fighter(self, name, *, slug=None, nickname=None, first=None, last=None):
        parts = name.split()
        return {"fighter_id": "1", "name": name, "first_name": first if first is not None else parts[0],
                "last_name": last if last is not None else (" ".join(parts[1:]) or None),
                "nickname": nickname, "espn_slug": slug}

    def test_a_plain_name_is_its_espn_slug_then_the_nickname_form_then_the_aliases(self):
        fighter = fighters.parse_athlete(espn_json("athlete_4412813.json"), None, fetched_utc=NOW, source_url="u")
        self.assertEqual(ufccom.slug_candidates(fighter), [
            "ismail-naurdiev", "ismail-naurdiev-austrian-wonderboy", "ismail-naurdiev-0", "ismail-naurdiev-1"])

    def test_a_suffix_is_tried_as_given_and_without(self):
        fighter = fighters.parse_athlete(espn_json("w2_athlete_5088844.json"), None, fetched_utc=NOW, source_url="u")
        self.assertEqual(ufccom.slug_candidates(fighter)[:2], ["raul-rosas-jr", "raul-rosas"])
        stale = dict(fighter, espn_slug="raul-rosas")
        self.assertEqual(ufccom.slug_candidates(stale)[:2], ["raul-rosas", "raul-rosas-jr"])
        for text, want in (("Michael Johnson II", ["michael-johnson-ii", "michael-johnson"]),
                           ("Kevin Lee Sr.", ["kevin-lee-sr", "kevin-lee"])):
            self.assertEqual(ufccom.slug_candidates(self.fighter(text))[:2], want)

    def test_accents_are_folded_in_the_name_and_ESPNs_own_slug_leads(self):
        fighter = fighters.parse_athlete(espn_json("w2_athlete_4274796.json"), None, fetched_utc=NOW, source_url="u")
        self.assertEqual(ufccom.slug_candidates(fighter)[0], "roberto-soldic")
        no_slug = dict(fighter, espn_slug=None)
        self.assertEqual(ufccom.slug_candidates(no_slug)[0], "roberto-soldic")
        self.assertEqual(ufccom.slug_candidates(self.fighter("Jiří Procházka"))[0], "jiri-prochazka")
        self.assertEqual(ufccom.slug_candidates(self.fighter("Jan Błachowicz"))[0], "jan-blachowicz")
        self.assertEqual(ufccom.slug_candidates(self.fighter("José Aldo"))[0], "jose-aldo")

    def test_two_part_and_hyphenated_surnames_get_shortened_variants_after_the_full_name(self):
        fighter = fighters.parse_athlete(espn_json("w2_athlete_5345639.json"), None, fetched_utc=NOW, source_url="u")
        got = ufccom.slug_candidates(fighter)
        self.assertEqual(got[0], "ilimbek-akylbek-uulu")
        self.assertIn("ilimbek-akylbek", got)
        self.assertIn("ilimbek-uulu", got)
        self.assertLess(got.index("ilimbek-akylbek-uulu"), got.index("ilimbek-akylbek"))
        hyphen = ufccom.slug_candidates(self.fighter("Waldo Cortes-Acosta"))
        self.assertEqual(hyphen[0], "waldo-cortes-acosta")
        self.assertIn("waldo-cortes", hyphen)
        self.assertIn("waldo-acosta", hyphen)

    def test_surname_particles_may_be_dropped_but_never_stand_alone(self):
        got = ufccom.slug_candidates(self.fighter("Rafael Dos Anjos"))
        self.assertEqual(got[0], "rafael-dos-anjos")
        self.assertIn("rafael-anjos", got)
        self.assertNotIn("rafael-dos", got)

    def test_initials_are_joined_first_and_then_spelled_out(self):
        got = ufccom.slug_candidates(self.fighter("T.J. Dillashaw", first="T.J.", last="Dillashaw"))
        self.assertEqual(got[:2], ["tj-dillashaw", "t-j-dillashaw"])
        self.assertEqual(ufccom.slug_candidates(self.fighter("TJ Dillashaw"))[0], "tj-dillashaw")

    def test_an_apostrophe_is_dropped_and_also_tried_as_a_hyphen(self):
        got = ufccom.slug_candidates(self.fighter("Sean O'Malley"))
        self.assertEqual(got[0], "sean-omalley")
        self.assertIn("sean-o-malley", got)

    def test_a_nickname_slug_separates_two_men_of_one_name(self):
        got = ufccom.slug_candidates(self.fighter("Bruno Silva", nickname="Blindado", slug="bruno-silva"))
        self.assertEqual(got, ["bruno-silva", "bruno-silva-blindado", "bruno-silva-0", "bruno-silva-1"])
        self.assertEqual(ufccom.slug_candidates(self.fighter("Anderson Silva", nickname="The Spider"))[1],
                         "anderson-silva-spider")

    def test_a_mononym_has_a_slug(self):
        fighter = fighters.parse_athlete(espn_json("w2_athlete_3154389.json"), None, fetched_utc=NOW, source_url="u")
        self.assertEqual(ufccom.slug_candidates(fighter)[0], "alatengheili")

    def test_candidates_are_unique_safe_and_limited(self):
        fighters_ = [fighters.parse_athlete(espn_json(n), None, fetched_utc=NOW, source_url="u") for n in (
            "athlete_4412813.json", "w2_athlete_5088844.json", "w2_athlete_4274796.json", "w2_athlete_5345639.json")]
        fighters_ += [self.fighter("Rafael Dos Anjos"), self.fighter("T.J. Dillashaw", first="T.J.", last="Dillashaw"),
                      self.fighter("Sean O'Malley", nickname="Sugar")]
        for fighter in fighters_:
            got = ufccom.slug_candidates(fighter)
            self.assertEqual(got, list(dict.fromkeys(got)), fighter["name"])
            self.assertLessEqual(len(got), ufccom.MAX_SLUG_CANDIDATES)
            for slug in got:
                self.assertRegex(slug, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertEqual(len(ufccom.slug_candidates(fighters_[0], limit=2)), 2)
        self.assertEqual(ufccom.slug_candidates(fighters_[0], limit=0), [])

    def test_nothing_unsafe_reaches_a_url(self):
        evil = self.fighter("Evil Name", slug="../../admin?x=1")
        self.assertEqual(ufccom.slug_candidates(evil)[0], "evil-name")
        self.assertEqual(ufccom.slug_candidates({"name": "艾拉 王"}), [])       # no Latin letters, nothing to build
        self.assertEqual(ufccom.slug_candidates({}), [])


class _Response:
    def __init__(self, status, body):
        self.status = status
        self._body = body
        message = email.message.Message()
        message["content-type"] = "text/html"
        self.headers = message

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ServedOpener:
    def __init__(self):
        self.routes = {}
        self.calls = []

    def serve(self, url, body=b"", *, status=200):
        self.routes[http.canonical_url(url)] = (status, body)

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected request (no network in tests): {url}")
        status, body = self.routes[url]
        if status == 200:
            return _Response(200, body)
        raise urllib.error.HTTPError(url, status, "err", email.message.Message(), io.BytesIO(b""))


CHALLENGE = b"<html><title>Just a moment...</title><body>Checking your browser before accessing</body></html>"


def minimal_page(name, record="21-4-0 (W-L-D)", slug=None):
    link = f'<link rel="canonical" href="https://www.ufc.com/athlete/{slug}" />' if slug else ""
    return (f'<html><head>{link}</head><body><h1 class="hero-profile__name">{name}</h1>'
            f'<p class="hero-profile__division-body">{record}</p></body></html>').encode("utf-8")


def fighter_from(athlete_file, *, records_file=None, record=None, **overrides):
    fighter = fighters.parse_athlete(espn_json(athlete_file), espn_json(records_file) if records_file else None,
                                     fetched_utc=NOW, source_url="u")
    if record is not None:
        fighter["record"] = record
    fighter.update(overrides)
    return fighter


def synthetic_fighter(fid, name, record, *, nickname=None, slug=None):
    first, _, last = name.partition(" ")
    athlete = {"id": fid, "displayName": name, "fullName": name, "firstName": first, "lastName": last,
               "shortName": f"{first[0]}. {last}", "nickname": nickname, "slug": slug}
    fighter = fighters.parse_athlete(athlete, None, fetched_utc=NOW, source_url="u")
    fighter["record"] = record
    return fighter


class FetchProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.opener = ServedOpener()
        self.fetcher = http.PoliteFetcher(cache_dir=Path(self.tmp.name), opener=self.opener, sleep=lambda s: None,
                                          now_iso=lambda: NOW)

    def serve(self, slug, body, *, status=200):
        self.opener.serve(espn_urls.ufccom_athlete(slug), body, status=status)

    def called(self, slug):
        return http.canonical_url(espn_urls.ufccom_athlete(slug)) in self.opener.calls

    def test_naurdiev_from_ESPN_to_a_stored_profile(self):
        fighter = fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json")
        self.serve("ismail-naurdiev", page_bytes("athlete_ismail-naurdiev.html"))
        record = ufccom.fetch_profile(self.fetcher, fighter)
        self.assertEqual(len(self.opener.calls), 1)
        self.assertEqual(set(record), {"fighter_id", "source_url", "fetched_utc", "matched_on"} | set(ufccom.PROFILE_FIELDS))
        self.assertEqual((record["fighter_id"], record["ufc_slug"], record["fetched_utc"], record["matched_on"]),
                         ("4412813", "ismail-naurdiev", NOW, "name+record"))
        self.assertEqual(record["source_url"], espn_urls.ufccom_athlete("ismail-naurdiev"))
        want = dict(PAGES["athlete_ismail-naurdiev.html"])
        self.assertEqual({k: record[k] for k in want}, want)

    def test_every_saved_page_is_accepted_for_its_own_fighter_and_stored_by_fighter_id(self):
        cases = [
            (fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json"), "ismail-naurdiev",
             "athlete_ismail-naurdiev.html", "name+record"),
            (fighter_from("w2_athlete_2447641.json"), "jose-aldo", "w2_athlete_jose-aldo.html", "name"),
            (fighter_from("w2_athlete_5450121.json", records_file="w2_athlete_5450121_records.json"), "lucas-armand",
             "w2_athlete_lucas-armand.html", "name+record"),
            (fighter_from("w2_athlete_5088844.json", record={"wins": 13, "losses": 1, "draws": 0}), "raul-rosas-jr",
             "w2_athlete_raul-rosas-jr.html", "name+record"),
            (fighter_from("w2_athlete_2335447.json", records_file="w2_athlete_2335447_records.json"), "anderson-silva",
             "w2_athlete_anderson-silva.html", "name+record"),
        ]
        store = UfcStore(Path(self.tmp.name) / "ufc")
        records = []
        for fighter, slug, page, basis in cases:
            self.serve(slug, page_bytes(page))
            record = ufccom.fetch_profile(self.fetcher, fighter)
            self.assertIsNotNone(record, page)
            self.assertEqual((record["fighter_id"], record["ufc_slug"], record["matched_on"]),
                             (fighter["fighter_id"], slug, basis), page)
            records.append(record)
        self.assertEqual(store.upsert("ufccom_profiles", records), {"added": 5, "updated": 0, "unchanged": 0, "total": 5})
        self.assertEqual(store.profile_for()["5450121"]["wins_ko"], 5)
        self.assertIsNone(store.profile_for()["5450121"]["avg_fight_time_s"])

    def test_a_404_slug_falls_through_to_the_next(self):
        fighter = fighter_from("w2_athlete_5088844.json", record={"wins": 13, "losses": 1, "draws": 0}, espn_slug="raul-rosas")
        self.serve("raul-rosas", b"", status=404)
        self.serve("raul-rosas-jr", page_bytes("w2_athlete_raul-rosas-jr.html"))
        lookup = ufccom.lookup_profile(self.fetcher, fighter)
        self.assertEqual(lookup.record["ufc_slug"], "raul-rosas-jr")
        self.assertEqual(lookup.tried, [{"slug": "raul-rosas", "outcome": "not_found"},
                                        {"slug": "raul-rosas-jr", "outcome": "accepted"}])
        self.assertEqual(self.opener.calls, [http.canonical_url(espn_urls.ufccom_athlete(s)) for s in ("raul-rosas", "raul-rosas-jr")])

    def test_when_every_slug_is_a_404_the_answer_is_none_and_every_slug_was_tried(self):
        fighter = fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json")
        slugs = ufccom.slug_candidates(fighter)
        for slug in slugs:
            self.serve(slug, b"", status=404)
        lookup = ufccom.lookup_profile(self.fetcher, fighter)
        self.assertIsNone(lookup.record)
        self.assertEqual([t["slug"] for t in lookup.tried], slugs)
        self.assertEqual({t["outcome"] for t in lookup.tried}, {"not_found"})
        self.assertIsNone(ufccom.fetch_profile(self.fetcher, fighter))
        self.assertEqual(len(self.opener.calls), len(slugs))          # the second lookup was all cached 404s

    def test_a_page_for_someone_else_is_rejected_and_never_stored(self):
        vettori = fighter_from("athlete_4001851.json", records_file="athlete_4001851_records.json")
        self.serve("marvin-vettori", page_bytes("w2_athlete_jose-aldo.html"))       # the wrong man's page
        for slug in ufccom.slug_candidates(vettori)[1:]:
            self.serve(slug, b"", status=404)
        lookup = ufccom.lookup_profile(self.fetcher, vettori)
        self.assertIsNone(lookup.record)
        self.assertEqual(lookup.tried[0], {"slug": "marvin-vettori", "outcome": "name_mismatch"})

    def test_a_wrong_page_is_skipped_and_the_right_one_found_further_down(self):
        naurdiev = fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json")
        self.serve("ismail-naurdiev", page_bytes("w2_athlete_isaac-vallie-flagg.html"))      # another fighter, HTTP 200
        self.serve("ismail-naurdiev-austrian-wonderboy", page_bytes("athlete_ismail-naurdiev.html"))
        lookup = ufccom.lookup_profile(self.fetcher, naurdiev)
        self.assertEqual([t["outcome"] for t in lookup.tried], ["name_mismatch", "accepted"])
        self.assertEqual(lookup.record["fighter_id"], "4412813")
        self.assertEqual(lookup.record["page_name"], "Ismail Naurdiev")

    def test_the_search_page_UFC_serves_instead_of_a_404_is_not_a_profile(self):
        fighter = fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json")
        self.serve("ismail-naurdiev", page_bytes("w2_search_results_unknown_slug.html"))
        self.serve("ismail-naurdiev-austrian-wonderboy", page_bytes("athlete_ismail-naurdiev.html"))
        lookup = ufccom.lookup_profile(self.fetcher, fighter)
        self.assertEqual([t["outcome"] for t in lookup.tried], ["no_name", "accepted"])
        self.assertEqual(lookup.record["ufc_slug"], "ismail-naurdiev")      # the page's own canonical slug

    def test_a_fighter_UFC_com_does_not_have_gets_none_from_the_pages_it_really_serves(self):
        # Captured live: a missing slug is the search page, and /ismail-naurdiev-0 was another fighter.
        fighter = fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json")
        slugs = ufccom.slug_candidates(fighter)
        self.assertEqual(slugs[2], "ismail-naurdiev-0")
        for slug in slugs:
            self.serve(slug, page_bytes("w2_athlete_isaac-vallie-flagg.html" if slug.endswith("-0")
                                        else "w2_search_results_unknown_slug.html"))
        lookup = ufccom.lookup_profile(self.fetcher, fighter)
        self.assertIsNone(lookup.record)
        self.assertEqual([t["outcome"] for t in lookup.tried], ["no_name", "no_name", "name_mismatch", "no_name"])

    def test_two_men_of_one_name_are_told_apart_by_their_records(self):
        blindado = synthetic_fighter("b2", "Bruno Silva", {"wins": 23, "losses": 13, "draws": 0},
                                     nickname="Blindado", slug="bruno-silva")
        self.serve("bruno-silva", page_bytes("w2_athlete_bruno-silva.html"))                # the flyweight: 15-9-2
        self.serve("bruno-silva-blindado", page_bytes("w2_athlete_bruno-silva-blindado.html"))
        lookup = ufccom.lookup_profile(self.fetcher, blindado)
        self.assertEqual(lookup.tried, [{"slug": "bruno-silva", "outcome": "record_mismatch"},
                                        {"slug": "bruno-silva-blindado", "outcome": "accepted"}])
        self.assertEqual((lookup.record["page_nickname"], lookup.record["record"]["losses"], lookup.record["ufc_slug"]),
                         ("Blindado", 13, "bruno-silva-blindado"))
        # and the flyweight is accepted on the first page, with no further request
        self.opener.calls.clear()
        bulldog = synthetic_fighter("b1", "Bruno Silva", {"wins": 15, "losses": 9, "draws": 2}, nickname="Bulldog", slug="bruno-silva")
        record = ufccom.fetch_profile(self.fetcher, bulldog)
        self.assertEqual((record["page_nickname"], record["ufc_slug"], record["matched_on"]), ("Bulldog", "bruno-silva", "name+record"))
        self.assertEqual(self.opener.calls, [])           # the page came from the cache

    def test_the_dash_zero_alias_is_stored_under_the_canonical_slug(self):
        blindado = synthetic_fighter("b2", "Bruno Silva", {"wins": 23, "losses": 13, "draws": 0})      # no nickname to build a slug from
        self.serve("bruno-silva", page_bytes("w2_athlete_bruno-silva.html"))
        self.serve("bruno-silva-0", page_bytes("w2_athlete_bruno-silva-blindado.html"))
        record = ufccom.fetch_profile(self.fetcher, blindado)
        self.assertEqual(record["ufc_slug"], "bruno-silva-blindado")
        self.assertEqual(record["source_url"], espn_urls.ufccom_athlete("bruno-silva-0"))

    def test_a_record_a_fight_or_two_apart_is_accepted_and_further_is_not(self):
        self.serve("ismail-naurdiev", page_bytes("athlete_ismail-naurdiev.html"))        # the page says 25-8-0
        for wins, losses, accepted in ((25, 8, True), (24, 8, True), (25, 9, True), (23, 8, True),
                                       (26, 9, True), (22, 8, False), (25, 11, False), (10, 3, False)):
            fighter = fighter_from("athlete_4412813.json", record={"wins": wins, "losses": losses, "draws": 0})
            for slug in ufccom.slug_candidates(fighter)[1:]:
                self.serve(slug, b"", status=404)
            got = ufccom.fetch_profile(self.fetcher, fighter)
            self.assertEqual(got is not None, accepted, (wins, losses))
        self.assertEqual(ufccom.RECORD_TOLERANCE, 2)

    def test_without_a_record_on_either_side_the_name_alone_decides_and_says_so(self):
        fighter = fighter_from("athlete_4412813.json")          # no records fetched: record is null
        self.assertIsNone(fighter["record"])
        self.serve("ismail-naurdiev", page_bytes("athlete_ismail-naurdiev.html"))
        self.assertEqual(ufccom.fetch_profile(self.fetcher, fighter)["matched_on"], "name")
        garbage = fighter_from("athlete_4001851.json", record={"wins": 19, "losses": 10, "draws": 1})
        self.serve("marvin-vettori", minimal_page("Marvin Vettori", record="no record shown"))
        self.assertEqual(ufccom.fetch_profile(self.fetcher, garbage)["matched_on"], "name")

    def test_spelling_differences_that_are_not_differences_still_match(self):
        cases = [
            (synthetic_fighter("1", "José Aldo", None, slug="jose-aldo"), "Jose Aldo"),
            (synthetic_fighter("2", "Roberto Soldić", None, slug="roberto-soldic"), "Roberto Soldic"),
            (synthetic_fighter("3", "TJ Dillashaw", None, slug="tj-dillashaw"), "T.J. Dillashaw"),
            (synthetic_fighter("4", "Raul Rosas Jr.", None, slug="raul-rosas-jr"), "Raul Rosas"),
            (synthetic_fighter("5", "Rafael Dos Anjos", None, slug="rafael-dos-anjos"), "Rafael dos Anjos"),
        ]
        for fighter, page_name in cases:
            self.serve(fighter["espn_slug"], minimal_page(page_name))
            self.assertIsNotNone(ufccom.fetch_profile(self.fetcher, fighter), (fighter["name"], page_name))

    def test_initials_match_whichever_way_the_aliases_were_built(self):
        # Aliases handed in by some other code path, not by alias_forms: only the page-side and
        # alias-side joining of initials can make "T.J." meet "TJ".
        for number, (aliases, page_name) in enumerate(((["t j dillashaw"], "TJ Dillashaw"),
                                                       (["tj dillashaw"], "T.J. Dillashaw"),
                                                       (["c b dollaway"], "CB Dollaway"))):
            slug = f"some-slug-{number}"                     # one URL per case: the fetcher caches by URL
            fighter = {"fighter_id": "7", "name": "x", "espn_slug": slug, "aliases": aliases}
            self.serve(slug, minimal_page(page_name))
            self.serve("x", b"", status=404)
            self.assertIsNotNone(ufccom.fetch_profile(self.fetcher, fighter), (aliases, page_name))

    def test_names_that_really_differ_do_not_match(self):
        for ours, page_name in (("Anderson Silva", "Bruno Silva"), ("Ismail Naurdiev", "Naurdiev Ismailov"),
                                ("Marvin Vettori", "Marvin Vettori Jr."), ("Alatengheili", "Alateng Heili")):
            fighter = synthetic_fighter("9", ours, None, slug="x-slug")
            fighter["aliases"] = fighters.alias_forms({"displayName": ours, "fullName": ours, "firstName": ours.split()[0],
                                                       "lastName": " ".join(ours.split()[1:])})
            self.serve("x-slug", minimal_page(page_name))
            for other in ufccom.slug_candidates(fighter)[1:]:
                self.serve(other, b"", status=404)
            self.assertIsNone(ufccom.fetch_profile(self.fetcher, fighter), (ours, page_name))

    def test_a_browser_check_stops_everything_and_later_slugs_are_never_requested(self):
        fighter = fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json")
        self.serve("ismail-naurdiev", CHALLENGE)
        for slug in ufccom.slug_candidates(fighter)[1:]:
            self.serve(slug, page_bytes("athlete_ismail-naurdiev.html"))
        with self.assertRaises(http.SourceBlocked):
            ufccom.fetch_profile(self.fetcher, fighter)
        self.assertEqual(len(self.opener.calls), 1)

    def test_a_403_and_the_request_cap_propagate_too(self):
        fighter = fighter_from("athlete_4412813.json")
        self.serve("ismail-naurdiev", b"", status=403)
        with self.assertRaises(http.FetchError) as caught:
            ufccom.fetch_profile(self.fetcher, fighter)
        self.assertEqual(caught.exception.status, 403)
        capped = http.PoliteFetcher(cache_dir=Path(self.tmp.name) / "capped", opener=self.opener, sleep=lambda s: None,
                                    now_iso=lambda: NOW, max_requests=1)
        for slug in ufccom.slug_candidates(fighter):
            self.serve(slug, b"", status=404)
        with self.assertRaises(http.RequestCapReached):
            ufccom.fetch_profile(capped, fighter)

    def test_max_age_makes_a_stale_cached_profile_refetch(self):
        fighter = fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json")
        self.serve("ismail-naurdiev", page_bytes("athlete_ismail-naurdiev.html"))
        ufccom.fetch_profile(self.fetcher, fighter)
        ufccom.fetch_profile(self.fetcher, fighter)
        self.assertEqual(len(self.opener.calls), 1)
        ufccom.fetch_profile(self.fetcher, fighter, max_age_s=60)
        self.assertEqual(len(self.opener.calls), 2)

    def test_a_fighter_without_an_id_or_a_name_is_an_error_not_a_blind_fetch(self):
        with self.assertRaises(ValueError):
            ufccom.fetch_profile(self.fetcher, {"name": "No Id"})
        with self.assertRaises(ValueError):
            ufccom.fetch_profile(self.fetcher, {"fighter_id": "1", "espn_slug": "x"})
        self.assertEqual(self.opener.calls, [])

    def test_explicit_candidates_override_the_generated_ones(self):
        fighter = fighter_from("athlete_4412813.json", records_file="athlete_4412813_records.json")
        self.serve("ismail-naurdiev-custom", page_bytes("athlete_ismail-naurdiev.html"))
        lookup = ufccom.lookup_profile(self.fetcher, fighter, candidates=["ismail-naurdiev-custom"])
        self.assertEqual([t["slug"] for t in lookup.tried], ["ismail-naurdiev-custom"])
        self.assertIsNotNone(lookup.record)


if __name__ == "__main__":
    unittest.main()
