"""Regression tests for LINEHOUND's pre-ship QA of the kennel-first rebuild, 2026-10-21 (branch fix/qa-open).

Each class pins one reported defect and fails against the code before the fix:

  AccountRoutesAreKennelFirst   index.html#/account and #/billing opened as the old picks shell (sport tabs, news strip, Gameday tab bar)
                                with no five-place nav; shot sw_comped_390_index_html_account.
  TheStandardPlanIsNotFounding  the $19.99 plan was labelled "Founding access" straight above the real $14.99 founding line; shot 36.
  KeepIsOneShot                 after a successful Keep the button stayed live, and a second tap showed the raw "name: is already taken"; shot 31b.
  LiveOffersOnlyHoundsThatBetTheSport / SendIsSecondary / AdminHasTheFooter    the three LOW items.
  TheNamePromptIsCompactAndBelowTheHounds    owner add-on: the member's hound is the product, so it sits above the name prompt.
"""
from __future__ import annotations

import re
import unittest

from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page
from tests.test_hounds_builder_web import CLICK_BLANK, SIGNED, base_routes, build, posts_to
from tests.test_hounds_builder_web import q as bq
from tests.test_live_board import DOG, RETIRED, TOKEN_KEY, board, hook
from tests.test_live_board import q as lq

NAME = [dict(do="set", sel="[data-hook='f-name']", value="  Pup Test  "), dict(do="set", sel="[data-hook='f-tagline']", value="Fetches")]


def read(*parts):
    return WEB.joinpath(*parts).read_text(encoding="utf-8")


def strip_comments(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


# ---------------------------------------------------------------------------------------------------
# 1. the Account routes
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class AccountRoutesAreKennelFirst(unittest.TestCase):
    QS = [dict(name="tabs", sel="[data-hook='site-tabbar'] .lh-tab", mode="texts"),
          dict(name="links", sel=".lh-nav__links a", mode="texts"),
          dict(name="bottom", sel=".lh-nav", mode="attr", attr="data-bottom"),
          dict(name="current", sel="[data-hook='site-tabbar'] .lh-tab[aria-current='page']", mode="texts")]

    def run_index(self, hash_, **kw):
        return run_page("nav", page_html="index.html", pathname="/web/index.html", hash=hash_, queries=self.QS, **kw)

    def test_account_and_billing_show_the_five_places_and_the_phone_tab_bar_for_a_member(self):
        for route in ("#/account", "#/billing", "#/signin"):
            with self.subTest(route=route):
                out = self.run_index(route, **SIGNED)
                f = out["final"]
                # owner ruling 2026-10-21 (kennel front): My Kennel is the big button top-right and the filled centre tab, not one of the links
                self.assertEqual(f["links"], ["Create", "Live", "Leaderboard"])
                self.assertEqual(f["tabs"], ["Create", "Live", "My Kennel", "Leaderboard", "Account"])
                self.assertEqual(f["bottom"], "on")                                   # the page's own data-bottom="off" is overridden here
                self.assertEqual(out["bodyAttrs"].get("data-kennel-route"), "true")   # the stylesheet hides the picks shell on this flag
                self.assertEqual(f["current"], ["Account"])                           # and Account is the place it names

    def test_a_visitor_on_billing_gets_the_visitor_bar_and_tab_bar_too(self):
        out = self.run_index("#/billing")
        self.assertEqual(out["final"]["tabs"], ["Leaderboard", "Live", "Sign in", "Make your first hound"])
        self.assertEqual(out["bodyAttrs"].get("data-kennel-route"), "true")

    def test_the_picks_routes_keep_the_member_apps_own_tab_bar(self):
        for route in ("", "#/today", "#/record-card"):
            with self.subTest(route=route):
                out = self.run_index(route, **SIGNED)
                self.assertEqual(out["final"]["tabs"], [])
                self.assertEqual(out["final"]["bottom"], "off")
                self.assertNotIn("data-kennel-route", out["bodyAttrs"])

    def test_the_stylesheet_hides_the_sport_tabs_the_news_strip_and_the_gameday_tab_bar_on_those_routes(self):
        css = strip_comments(read("css", "lhnav.css"))
        m = re.search(r"body\[data-kennel-route\] \.appbar, body\[data-kennel-route\] \.news-host, body\[data-kennel-route\] \.tabbar \{ display: none; \}", css)
        self.assertIsNotNone(m, "no rule hides .appbar (sport tabs), .news-host and .tabbar on the kennel routes")
        index = read("index.html")
        for hook_ in ('class="appbar"', 'class="news-host"', 'class="tabbar"'):
            self.assertIn(hook_, index)                     # the rule's three targets are what index.html really draws

    def test_the_route_is_re_read_when_the_hash_changes(self):
        js = strip_comments(read("js", "nav.js"))
        self.assertIn('window.addEventListener("hashchange", again)', js)


# ---------------------------------------------------------------------------------------------------
# 2. the $19.99 plan is not "Founding"
# ---------------------------------------------------------------------------------------------------

class TheStandardPlanIsNotFounding(unittest.TestCase):
    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_the_standard_plan_is_named_linehound_membership(self):
        out = run_js('import { BETA_TIER, PLAN_EYEBROW, foundingOfferLine } from "./pricing.js";\n'
                     'console.log(JSON.stringify({ name: BETA_TIER.name, price: BETA_TIER.price_cents, display: BETA_TIER.price_display, '
                     'note: BETA_TIER.billing_note, eyebrow: PLAN_EYEBROW, line: foundingOfferLine({ priceCents: 1499, cap: 50, left: 19 }) }));')
        self.assertEqual(out["name"], "LINEHOUND membership")
        self.assertEqual(out["eyebrow"], "MEMBERSHIP")
        self.assertEqual((out["price"], out["display"]), (1999, "$19.99/mo"))           # the price itself is unchanged
        self.assertEqual(out["line"], "Founding member: $14.99/mo for life · 19 of 50 left")   # the founding offer keeps its word

    def test_no_page_script_calls_the_standard_plan_founding_access(self):
        offenders = []
        for path in sorted((WEB / "js").glob("*.js")):
            if path.name == "betcheck.js":                  # a legacy page that is never advertised; left alone on purpose
                continue
            if re.search(r"founding access", strip_comments(path.read_text(encoding="utf-8")), re.I):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_the_signup_card_eyebrow_is_membership_in_every_state(self):
        js = strip_comments(read("js", "signup.js"))
        self.assertEqual(len(re.findall(r"signup-card__eyebrow", js)), 4)
        self.assertEqual(len(re.findall(r"signup-card__eyebrow\", text: PLAN_EYEBROW", js)), 4)

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_the_billing_card_reads_membership_above_the_founding_member_line(self):
        out = run_page("nav", page_html="index.html", pathname="/web/index.html", hash="#/billing", queries=[])
        self.assertIsNotNone(out)          # (the card itself is drawn by billing.js from BETA_TIER.name, pinned above)
        billing = strip_comments(read("js", "billing.js"))
        self.assertIn('el("h2", { text: BETA_TIER.name })', billing)


# ---------------------------------------------------------------------------------------------------
# 2b. the billing card says which price Subscribe charges (owner follow-up 2026-10-21)
# ---------------------------------------------------------------------------------------------------

BILLING_HARNESS = r"""
class TextNode { constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; } }
class Elem {
  constructor(tag) { this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {}; this.childNodes = []; this.parentNode = null; this.listeners = {}; }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  byHook(name) { return this._all([]).filter((n) => n.attrs["data-hook"] === name); }
  byClass(name) { return this._all([]).filter((n) => String(n.attrs.class || "").split(" ").includes(name)); }
}
globalThis.document = { createElement: (t) => new Elem(t), createTextNode: (t) => new TextNode(t), addEventListener() {}, querySelector: () => null };
globalThis.window = { sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} }, localStorage: { getItem: () => "tok", setItem() {}, removeItem() {} },
  location: { search: "", hash: "", pathname: "/web/index.html", href: "" } };
globalThis.sessionStorage = globalThis.window.sessionStorage;
globalThis.localStorage = globalThis.window.localStorage;
const scenario = JSON.parse(process.env.SCENARIO);
globalThis.fetch = async (url) => {
  const body = String(url).includes("/billing/offer") ? scenario.offer : { status: "not_configured" };
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
};
const billing = await import("./billing.js");
const host = new Elem("div");
await billing.renderBilling(host);
const one = (name) => (host.byHook(name)[0] ? host.byHook(name)[0].textContent : null);
const price = host.byClass("billing__price")[0];
console.log("@@" + JSON.stringify({ h2: host.byClass("panel").length ? host._all([]).filter((n) => n.tagName === "H2").map((n) => n.textContent) : [],
  headline: price ? price.textContent : null, dataPrice: price ? price.attrs["data-price"] : null,
  seats: one("billing-seats"), offer: one("billing-founding-offer"), button: one("billing-subscribe"),
  notes: host.byClass("billing__note").map((n) => n.textContent) }));
"""


def run_billing(offer):
    import json as _json, os, shutil, subprocess, tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        for path in (WEB / "js").glob("*.js"):
            shutil.copy(path, tmp)
        Path(tmp, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(tmp, "harness.mjs").write_text(BILLING_HARNESS, encoding="utf-8")
        done = subprocess.run(["node", "harness.mjs"], cwd=tmp, capture_output=True, text=True, encoding="utf-8", timeout=60,
                              env=dict(os.environ, SCENARIO=_json.dumps({"offer": offer})))
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("@@")]
    assert lines, done.stderr[-1500:] + done.stdout[-500:]
    return _json.loads(lines[-1][2:])


SEAT = {"founding": {"price_cents": 1499, "cap": 50, "taken": 31, "left": 19, "reserved": 0, "available": True}, "standard": {"price_cents": 1999}}
NO_SEAT = {"founding": None, "standard": {"price_cents": 1999}}


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBillingCardNamesTheChargedPrice(unittest.TestCase):
    def test_with_a_founding_seat_the_card_headlines_the_founding_price_and_the_button_names_it(self):
        f = run_billing(SEAT)
        self.assertEqual(f["headline"], "$14.99/mo · Founding member")
        self.assertEqual(f["seats"], "19 of 50 founding seats left. After that, $19.99/mo.")
        self.assertIn("7-day free trial, then $14.99/month. Cancel anytime.", f["notes"])
        self.assertNotIn("$19.99/month", " ".join(f["notes"]))                 # the trial sentence no longer quotes the other price
        self.assertIn("Your price stays $14.99 for as long as you stay subscribed", f["offer"])      # the fine print stays
        self.assertEqual(f["button"], "Subscribe at $14.99")
        self.assertEqual(f["h2"], ["LINEHOUND membership"])

    def test_with_no_seat_it_is_the_standard_only_card_it_always_was(self):
        for offer in (NO_SEAT, {"founding": {"price_cents": 1499, "cap": 50, "left": 0, "available": False}}):
            f = run_billing(offer)
            self.assertEqual(f["headline"], "$19.99/mo")
            self.assertIsNone(f["seats"])
            self.assertEqual(f["notes"], ["7-day free trial, then $19.99/month. Cancel anytime."])
            self.assertEqual(f["offer"], "")
            self.assertEqual(f["button"], "Subscribe")
            self.assertNotIn("ounding", " ".join(filter(None, [f["headline"], f["button"], f["offer"]] + f["notes"])))

    def test_the_card_is_drawn_once_with_the_price_it_charges_never_filled_in_afterwards(self):
        js = strip_comments(read("js", "billing.js"))
        self.assertIn("subscribeCopy(await loadFoundingOffer())", js)
        self.assertNotIn(".then((founding)", js)

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_the_copy_helper_is_pure_and_the_standard_note_is_the_plan_note(self):
        out = run_js('import { subscribeCopy, trialNote, BETA_TIER } from "./pricing.js";\n'
                     'console.log(JSON.stringify({ std: trialNote(1999) === BETA_TIER.billing_note, none: subscribeCopy(null), '
                     'one: subscribeCopy({ priceCents: 1499, cap: 50, left: 1 }) }));')
        self.assertTrue(out["std"])
        self.assertEqual(out["none"]["button"], "Subscribe")
        self.assertEqual(out["one"]["subline"], "1 of 50 founding seats left. After that, $19.99/mo.")


# ---------------------------------------------------------------------------------------------------
# 3. Keep in the builder
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class KeepIsOneShot(unittest.TestCase):
    KEPT = {"hound": {"id": "u-x", "name": "Pup Test"}}

    def kept_build(self, extra=(), **routes):
        r = base_routes(**{"POST /hounds": [200, self.KEPT]}, **routes)
        return build(r, **SIGNED, actions=[CLICK_BLANK] + NAME + [dict(do="click", sel="[data-hook='build-submit']", wait=200)] + list(extra),
                     queries=[bq("btn", "[data-hook='build-submit']"), bq("kept", "[data-hook='build-submit']", "attr", attr="data-kept"),
                              bq("disabled", "[data-hook='build-submit']", "disabled")])

    def test_after_a_successful_keep_the_button_opens_my_kennel(self):
        out = self.kept_build()
        self.assertEqual(len(posts_to(out, "/hounds")), 1)
        self.assertEqual(out["final"]["btn"], "Open in My Kennel")
        self.assertEqual(out["final"]["kept"], "true")
        self.assertFalse(out["final"]["disabled"])

    def test_tapping_it_goes_to_my_kennel_and_never_posts_a_second_hound(self):
        out = self.kept_build([dict(do="click", sel="[data-hook='build-submit']", wait=100)])
        self.assertEqual(len(posts_to(out, "/hounds")), 1)
        self.assertEqual(out["navigations"], ["kennel.html"])

    def test_a_new_name_brings_keep_back(self):
        out = self.kept_build([dict(do="set", sel="[data-hook='f-name']", value="Second Pup", wait=60)])
        self.assertTrue(out["final"]["btn"].startswith("Keep "), out["final"]["btn"])
        self.assertEqual(out["final"]["kept"], "false")

    def test_the_servers_name_taken_refusal_is_said_in_the_builders_words(self):
        routes = base_routes(**{"POST /hounds": [422, {"detail": {"error": "spec_invalid", "fields": {"name": "is already taken"}}}]})
        out = build(routes, **SIGNED, actions=[CLICK_BLANK] + NAME + [dict(do="click", sel="[data-hook='build-submit']", wait=200)],
                    queries=[bq("save", "[data-hook='build-save-problems']"), bq("problems", "[data-hook='build-problems']")])
        for box in ("save", "problems"):
            self.assertIn("That name is taken. Try another.", out["final"][box])
            self.assertNotIn("is already taken", out["final"][box])

    def test_a_failed_keep_leaves_the_button_as_keep(self):
        out = build(base_routes(**{"POST /hounds": [500, {}]}), **SIGNED, actions=[CLICK_BLANK] + NAME + [dict(do="click", sel="[data-hook='build-submit']", wait=200)],
                    queries=[bq("btn", "[data-hook='build-submit']")])
        self.assertTrue(out["final"]["btn"].startswith("Keep "))


# ---------------------------------------------------------------------------------------------------
# 4. LOW: Live and admin
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE, "node not installed")
class LiveOffersOnlyHoundsThatBetTheSport(unittest.TestCase):
    SEND = "[data-hook='live-send'][data-event='{}']"
    MLB = dict(DOG, sports=["mlb"])
    HOCKEY = dict(DOG, id="u-3", name="Puck Pete", sports=["hockey", "soccer"])

    def tray(self, event, dogs):
        routes = {"/hounds/camp/mine": [200, {"dogs": dogs, "count": len(dogs)}]}
        return board(routes, stored={TOKEN_KEY: "tok"}, actions=[dict(do="click", sel=self.SEND.format(event), wait=100)],
                     queries=[lq("dogs", hook("live-dog"), "texts"), lq("none", hook("live-no-sport-dogs")), lq("ask", ".lv-tray__ask")])

    def test_an_mlb_hound_is_not_offered_for_hockey(self):
        out = self.tray("hoc-1", [self.MLB, self.HOCKEY])
        self.assertEqual(out["final"]["dogs"], ["Puck Pete Running"])

    def test_no_qualifying_hound_says_so_with_the_sport_named(self):
        out = self.tray("hoc-1", [self.MLB, dict(self.MLB, id="u-4", name="Second MLB")])
        self.assertEqual(out["final"]["dogs"], [])
        self.assertIn("None of your hounds bet Hockey yet", out["final"]["none"])

    def test_a_hound_with_no_sports_listed_is_still_offered(self):
        out = self.tray("soc-4", [DOG])
        self.assertEqual(out["final"]["dogs"], ["Plus Money Pete Running"])

    def test_a_retired_hound_is_still_left_out(self):
        out = self.tray("hoc-1", [dict(RETIRED, sports=["hockey"])])
        self.assertEqual(out["final"]["dogs"], [])

    def test_the_server_names_each_hounds_sports_in_the_camp_list(self):
        src = strip_comments((WEB.parent / "src" / "hounds" / "interact" / "camp.py").read_text(encoding="utf-8").replace('"""', "'''"))
        self.assertIn('"sports": [str(x).lower()', src)


class SendIsSecondary(unittest.TestCase):
    def test_send_a_hound_is_a_quiet_secondary_button_not_a_filled_accent_one(self):
        css = strip_comments(read("css", "live.css"))
        rules = re.findall(r"\.hounds-page\.lv-page \.lv-send[^{]*\{([^}]*)\}", css)
        self.assertTrue(rules)
        for body in rules:
            self.assertNotIn("background: var(--lh-accent)", body)       # no solid green fill, hover or open
            self.assertNotIn("var(--lh-accent-soft)", body)              # and no green tint either


class AdminHasTheFooter(unittest.TestCase):
    def test_admin_carries_the_one_compliance_footer(self):
        src = read("admin.html")
        foot = re.search(r"<footer.*?</footer>", src, flags=re.S)
        self.assertIsNotNone(foot, "admin.html has no footer")
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", foot.group(0)))
        for part in ("21+", "Paper bets only, not advice", "Bet at your own risk", "Gamble responsibly.", "1-800-GAMBLER"):
            self.assertIn(part, text)
        self.assertEqual(len(re.findall(r"tel:1-800-426-2537", src)), 1)
        self.assertEqual(src.count("<footer"), 1)


# ---------------------------------------------------------------------------------------------------
# add-on: My Kennel's name prompt
# ---------------------------------------------------------------------------------------------------

class TheNamePromptIsCompactAndBelowTheHounds(unittest.TestCase):
    def test_the_slot_sits_after_the_hound_grid_and_the_tonight_strip_in_the_page(self):
        html = read("kennel.html")
        order = [html.index(f'data-hook="{h}"') for h in ("kennel-tonight-slot", "kennel-grid", "kennel-name-slot")]
        self.assertEqual(order, sorted(order))

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_the_first_hound_card_renders_above_the_name_prompt_in_dom_order(self):
        from tests.test_backtest_kennel_web import TheKennelNamePrompt
        from tests.test_kennel_page import SIGNED as KSIGNED
        out = run_page("kennel", routes=TheKennelNamePrompt().routes(), **KSIGNED, queries=[])
        hooks = out["hooks"]
        self.assertIn("kennel-name-prompt", hooks)
        self.assertIn("kennel-dog", hooks)
        self.assertLess(hooks.index("kennel-dog"), hooks.index("kennel-name-prompt"))

    @unittest.skipUnless(HAS_NODE, "node not installed")
    def test_the_prompt_is_one_heading_a_row_and_a_rules_toggle(self):
        from tests.test_backtest_kennel_web import TheKennelNamePrompt
        from tests.test_kennel_page import SIGNED as KSIGNED
        qs = [dict(name="rules", sel="[data-hook='kennel-name-rules'] summary", mode="text"),
              dict(name="row", sel="[data-hook='kennel-name-prompt'] .kn-nameform__row button", mode="texts"),
              dict(name="input", sel="[data-hook='kennel-name-input']", mode="count"),
              dict(name="inside", sel="[data-hook='kennel-name-rules'] p", mode="text")]
        f = run_page("kennel", routes=TheKennelNamePrompt().routes(), **KSIGNED, queries=qs)["final"]
        self.assertEqual(f["rules"], "rules")
        self.assertEqual(f["row"], ["Save name", "Not now"])
        self.assertEqual(f["input"], 1)
        self.assertIn("2 to 30 characters", f["inside"])               # the helper text lives behind the toggle, not beside the field


if __name__ == "__main__":
    unittest.main()
