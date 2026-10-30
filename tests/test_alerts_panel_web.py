"""Account -> Alerts (web/js/alerts.js), run for real under node against a fake DOM (tests/hounds_web_harness.mjs).

THE DEFECT (owner, on his iPhone, 2026-10-29: "this screen is buggy and glitchy"). The panel had no CSS at all, so it drew as
raw inline text (a checkbox mid-sentence, two identical "Send me a test alert" buttons, rows wrapping at random), it listed rows
that can never work ("The mobile app is not released yet", "Text alerts are not switched on yet"), and EVERY toggle tore the
whole panel down and rebuilt it (focus lost, the scroll position thrown, a half-typed phone number wiped).

WHAT IS PINNED
  * every channel and every alert type is a labelled switch (a real checkbox with role="switch"), label then switch then ONE
    muted note;
  * the mobile-app row is never drawn; the text-message row is drawn only when the server says texts are set up, and then the
    phone / code form is part of it;
  * a channel's test button shows only while the channel is on, and its words name the channel;
  * a toggle changes ITS row in place: the same DOM nodes before and after, the same request as before, a failed save puts the
    switch back, and a typed phone number survives another switch being flipped;
  * the private feed: the link on its own full-width line, Copy and Reset together on the line beneath, copy-once kept;
  * every class the script draws has a rule in web/css/signin.css (the panel shipped with none).

The payloads are shaped like api/alerts_routes.py _payload(); the availability words come from the REAL channel classes
(src/notify/alert_channels.py), so a change to what the server says about texts or the app reaches this file.

Skipped when node is not installed (the static checks need none).
"""

from __future__ import annotations

import re
import unittest

from src.notify import alert_channels as ch
from src.notify import alerts
from tests.hounds_web_runner import HAS_NODE, WEB, run_page

CONFIGURED = {ch.ENV_SID: "ACtest", ch.ENV_TOKEN: "tok_test", ch.ENV_FROM: "+15550001111"}
#: the page has already adopted this browser's zone, so the first load makes no PUT of its own
SEEN_ZONE = {"alerts-tz-adopted": "1"}
IOS_NOTE = ("On iPhone, add LINEHOUND to your Home Screen first (Share, then Add to Home Screen), "
            "then turn notifications on from the app icon.")


def q(name, sel, mode="text", attr=None):
    out = {"name": name, "sel": sel, "mode": mode}
    if attr:
        out["attr"] = attr
    return out


def _sms(mode, on=False):
    """The text-message entry. ``mode`` None = the server has no Twilio keys; "plan" = set up, free member; "new" = set up,
    paid, no number yet; "pending" = a code was texted; "in" = a verified number."""
    entry = {"name": "sms", "label": ch.CHANNELS["sms"].label, **ch.CHANNELS["sms"].availability(CONFIGURED if mode else {}),
             "on": on, "has_target": mode == "in", "paid_only": True, "allowed": mode != "plan",
             "phone": "***-***-4321" if mode == "in" else None, "opted_in": mode == "in", "stopped": False,
             "pending_phone": "***-***-4321" if mode == "pending" else None}
    return entry


def state(*, sms=None, sms_on=False, email_on=False, push_on=False, feed_allowed=True, feed_set=False, toggles=None,
          morning=True, quiet=(None, None)):
    native = ch.CHANNELS["native"]
    channels = [
        {"name": "email", "label": ch.CHANNELS["email"].label, "available": True, "reason": "", "on": email_on, "has_target": True},
        {"name": "push", "label": ch.CHANNELS["push"].label, "available": True, "reason": "", "on": push_on,
         "has_target": push_on, "public_key": "BPublicKeyForTests"},
        _sms(sms, sms_on),
        {"name": "native", "label": native.label, **native.availability(), "on": False, "has_target": False},
    ]
    return {
        "channels": channels, "events": "both", "event_toggles": {**alerts.DEFAULT_TOGGLES, **(toggles or {})},
        "event_channels": {kind: [c for c in alerts.CHANNEL_NAMES if kind in alerts.CHANNEL_KINDS[c] and c != "native"]
                           for kind in alerts.KINDS},
        "quiet_start": quiet[0], "quiet_end": quiet[1], "tz": "America/Los_Angeles", "morning_lineup": morning,
        "morning_hour": alerts.MORNING_HOUR, "feed": {"allowed": feed_allowed, "set": feed_set}, "sizing": {}, "paper_only": True,
        "ios_note": IOS_NOTE,
    }


def page(base, **scenario):
    """Mount the panel with GET /me/alerts answering ``base``."""
    routes = {"/me/alerts": [200, base]}
    routes.update(scenario.pop("routes", {}))
    scenario.setdefault("stored", SEEN_ZONE)
    # the words of the panel alone: the shell page it is mounted on has plenty of other text
    scenario["queries"] = list(scenario.pop("queries", [])) + [q("panel", "[data-hook='account-alerts']")]
    out = run_page("alerts", routes=routes, **scenario)
    out["panel"] = out["final"]["panel"] or ""
    return out


def after_put(new_state):
    """GET answers the first state; from the second call on (the toggle's PUT) the path answers ``new_state``."""
    return {"/me/alerts": [1, [200, new_state]]}


def puts(out):
    return [p for p in out["posts"] if p["method"] == "PUT" and p["url"] == "/me/alerts"]


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheRows(unittest.TestCase):
    def test_every_channel_and_alert_type_is_a_labelled_switch(self):
        out = page(state(), queries=[
            q("switches", "input[role='switch']", "count"), q("boxes", "input[type='checkbox']", "count"),
            q("ids", "input[role='switch']", "attrs", "id"), q("fors", "label", "attrs", "for"),
            q("types", "input[role='switch']", "attrs", "type"),
            q("hooks", "input[role='switch']", "attrs", "data-hook")])
        f = out["final"]
        # email, push, the morning note and the four bet alerts; no texts, no app
        self.assertEqual(f["switches"], 7)
        self.assertEqual(f["boxes"], 7, "a checkbox that is not a switch is sitting in the list")
        self.assertEqual(set(f["types"]), {"checkbox"}, "a switch is still a real checkbox")
        self.assertTrue(set(f["ids"]) <= set(f["fors"]), "every switch has a label that toggles it")
        self.assertEqual(f["hooks"], ["alerts-email-toggle", "alerts-push-toggle", "alerts-morning-toggle",
                                      "alerts-event-placed-toggle", "alerts-event-starting-toggle",
                                      "alerts-event-live-toggle", "alerts-event-settled-toggle"])

    def test_a_channel_row_is_label_switch_and_one_muted_note(self):
        out = page(state(), queries=[
            q("label", "[data-hook='alerts-email'] label"), q("note", "[data-hook='alerts-email-note']"),
            q("noteClass", "[data-hook='alerts-email-note']", "attr", "class"),
            q("rowClass", "[data-hook='alerts-email']", "attr", "class"),
            q("labelClass", "[data-hook='alerts-email'] label", "attr", "class"),
            q("switchClass", "[data-hook='alerts-email-toggle']", "attr", "class"),
            q("notes", "[data-hook='alerts-email'] .alerts__note", "count"),
            q("push", "[data-hook='alerts-push-note']"),
            q("ios", "[data-hook='alerts-ios-note']")])
        f = out["final"]
        self.assertEqual(f["label"], "Email")
        self.assertEqual(f["note"], "Off.")
        self.assertIn("alerts__note", f["noteClass"])
        self.assertIn("alerts__row", f["rowClass"])
        self.assertIn("alerts__label", f["labelClass"])
        self.assertIn("alerts__switch", f["switchClass"])
        self.assertEqual(f["notes"], 1)
        self.assertEqual(f["push"], "Switch on to allow notifications in this browser.")
        self.assertEqual(f["ios"], IOS_NOTE, "the iPhone note is still on the push row")

    def test_the_home_screen_note_shows_only_to_a_safari_tab_on_an_iphone(self):
        iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
        ask = [q("hidden", "[data-hook='alerts-ios-note']", "hidden"), q("text", "[data-hook='alerts-ios-note']")]
        elsewhere = page(state(), queries=ask)
        self.assertTrue(elsewhere["final"]["hidden"], "nobody off an iPhone needs the Home Screen step")
        in_safari = page(state(), queries=ask, userAgent=iphone, standalone=False)
        self.assertFalse(in_safari["final"]["hidden"])
        self.assertEqual(in_safari["final"]["text"], IOS_NOTE)
        installed = page(state(), queries=ask, userAgent=iphone, standalone=True)
        self.assertTrue(installed["final"]["hidden"], "already on the Home Screen")
        told = page(state(), userAgent=iphone, standalone=False,
                    actions=[{"do": "check", "sel": "[data-hook='alerts-push-toggle']"}],
                    queries=[q("status", "[data-hook='alerts-status']"), q("on", "[data-hook='alerts-push-toggle']", "checked")])
        self.assertIn("add LINEHOUND to your Home Screen first", told["final"]["status"])
        self.assertFalse(told["final"]["on"])

    def test_the_alert_types_and_the_morning_note_are_the_same_kind_of_row(self):
        out = page(state(), queries=[
            q("heading", "[data-hook='alerts-events'] .alerts__heading"),
            q("rows", "[data-hook='alerts-events'] .alerts__row", "count"),
            q("labels", "[data-hook='alerts-events'] label", "texts"),
            q("email_note", "[data-hook='alerts-event-starting'] .alerts__note"),
            q("checks", "[data-hook='alerts-events'] input[role='switch']", "checks")])
        f = out["final"]
        self.assertEqual(f["heading"], "Send me an alert when:")
        self.assertEqual(f["rows"], 5)
        self.assertEqual(f["labels"], ["Morning lineup", "Bet placed", "Starting soon", "Live updates", "Bet settled"])
        self.assertIn("Notifications and texts only, not email.", f["email_note"])
        self.assertEqual(f["checks"], [True, True, True, False, True], "the server's defaults: Live updates start off")

    def test_the_mobile_app_row_is_never_drawn(self):
        for label, base in (("texts off", state()), ("texts on", state(sms="new"))):
            with self.subTest(label):
                out = page(base)
                self.assertNotIn("alerts-native", out["hooks"])
                self.assertNotIn("alerts-native-toggle", out["hooks"])
                self.assertNotIn("alerts-native-note", out["hooks"])
                self.assertNotRegex(out["panel"], r"(?i)mobile app|not released")

    def test_there_is_no_text_message_row_when_the_server_has_no_texts(self):
        base = state()
        self.assertFalse(next(c for c in base["channels"] if c["name"] == "sms")["available"])
        out = page(base)
        for hook in ("alerts-sms", "alerts-sms-toggle", "alerts-sms-note", "alerts-sms-form", "alerts-sms-phone",
                     "alerts-sms-agree", "alerts-sms-test"):
            self.assertNotIn(hook, out["hooks"])
        self.assertNotRegex(out["panel"], r"(?i)not switched on|text messages|I agree to get text")
        self.assertIn("alerts-email", out["hooks"])
        self.assertIn("alerts-push", out["hooks"])

    def test_the_text_message_row_is_drawn_when_the_server_has_texts(self):
        base = state(sms="new")
        self.assertTrue(next(c for c in base["channels"] if c["name"] == "sms")["available"])
        out = page(base, queries=[
            q("label", "[data-hook='alerts-sms'] label"), q("note", "[data-hook='alerts-sms-note']"),
            q("disabled", "[data-hook='alerts-sms-toggle']", "disabled"),
            q("switch", "[data-hook='alerts-sms-toggle']", "attr", "role"),
            q("agreeRole", "[data-hook='alerts-sms-agree']", "attr", "role"),
            q("agreeType", "[data-hook='alerts-sms-agree']", "attr", "type"),
            q("formInRow", "[data-hook='alerts-sms'] [data-hook='alerts-sms-form']", "exists"),
            q("phoneType", "[data-hook='alerts-sms-phone']", "attr", "type"),
            q("consent", "[data-hook='alerts-sms-form'] label", "texts"),
            q("buttons", "[data-hook='alerts-sms-form'] button", "texts")])
        f = out["final"]
        self.assertEqual(f["label"], "Text messages")
        self.assertEqual(f["note"], "Add your number below to turn on texts.")
        self.assertTrue(f["disabled"], "no verified number yet, so the switch cannot be flipped")
        self.assertEqual(f["switch"], "switch")
        self.assertIsNone(f["agreeRole"], "the consent box is a plain checkbox, not a switch")
        self.assertEqual(f["agreeType"], "checkbox")
        self.assertTrue(f["formInRow"], "the phone form belongs to the text row")
        self.assertEqual(f["phoneType"], "tel")
        self.assertEqual(f["consent"], ["I agree to get text messages about my hounds' bets from LINEHOUND. "
                                        "Message and data rates may apply. Reply STOP to end."])
        self.assertEqual(f["buttons"], ["Text me a code"])

    def test_a_free_member_sees_the_plan_note_and_no_form_when_texts_are_set_up(self):
        out = page(state(sms="plan"), queries=[
            q("note", "[data-hook='alerts-sms-note']"), q("disabled", "[data-hook='alerts-sms-toggle']", "disabled")])
        self.assertEqual(out["final"]["note"], "Text alerts are part of the member plan.")
        self.assertTrue(out["final"]["disabled"])
        self.assertNotIn("alerts-sms-form", out["hooks"])

    def test_the_code_step_and_the_verified_number_lay_out_cleanly(self):
        pending = page(state(sms="pending"), queries=[
            q("note", "[data-hook='alerts-sms-note']"), q("code", "[data-hook='alerts-sms-code']", "attr", "autocomplete"),
            q("buttons", "[data-hook='alerts-sms-form'] button", "texts"), q("body", "[data-hook='alerts-sms-form'] p", "texts")])
        f = pending["final"]
        self.assertEqual(f["note"], "Type the code we texted you below.")
        self.assertEqual(f["code"], "one-time-code")
        self.assertEqual(f["buttons"], ["Check code and turn on texts", "Use a different number"])
        self.assertEqual(f["body"], ["We texted a 6-digit code to ***-***-4321. Type it here to turn texts on."])
        done = page(state(sms="in", sms_on=True), queries=[
            q("disabled", "[data-hook='alerts-sms-toggle']", "disabled"), q("checked", "[data-hook='alerts-sms-toggle']", "checked"),
            q("note", "[data-hook='alerts-sms-note']"), q("form", "[data-hook='alerts-sms-form']"),
            q("test", "[data-hook='alerts-sms-test']")])
        g = done["final"]
        self.assertFalse(g["disabled"])
        self.assertTrue(g["checked"])
        self.assertEqual(g["note"], "On.")
        self.assertIn("Texts go to ***-***-4321.", g["form"])
        self.assertIn("Remove my number", g["form"])
        self.assertEqual(g["test"], "Send a test text")

    def test_no_unfinished_or_forbidden_word_is_on_the_panel(self):
        for label, base in (("plain", state()), ("texts", state(sms="new")), ("members", state(sms="in", sms_on=True, push_on=True, email_on=True))):
            with self.subTest(label):
                text = page(base)["panel"]
                self.assertNotRegex(text, r"(?i)\b(beta|new|edge|lock|locked|undefined|null)\b")
                self.assertNotIn("not released", text.lower())


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheTestButtons(unittest.TestCase):
    def test_no_test_button_while_a_channel_is_off(self):
        out = page(state(), queries=[q("buttons", "[data-hook='alerts-body'] button", "count"),
                                     q("old", "button", "texts")])
        self.assertEqual(out["final"]["buttons"], 1, "only the feed's own button is on a quiet panel")
        self.assertNotIn("alerts-email-test", out["hooks"])
        self.assertNotIn("alerts-push-test", out["hooks"])
        self.assertNotIn("Send me a test alert", out["final"]["old"])

    def test_each_button_is_named_for_its_channel_and_there_is_one_per_channel(self):
        out = page(state(email_on=True, push_on=True, sms="in", sms_on=True), queries=[
            q("email", "[data-hook='alerts-email-test']"), q("push", "[data-hook='alerts-push-test']"),
            q("sms", "[data-hook='alerts-sms-test']"), q("tests", "button", "texts")])
        f = out["final"]
        self.assertEqual((f["email"], f["push"], f["sms"]), ("Send a test email", "Send a test notification", "Send a test text"))
        self.assertEqual(sum("test" in t.lower() for t in f["tests"]), 3)
        self.assertFalse(any("test alert" in t.lower() for t in f["tests"]), "no two identical buttons")
        self.assertNotIn("alerts-native-test", out["hooks"])

    def test_the_button_appears_when_the_channel_goes_on_and_goes_when_it_goes_off(self):
        on = page(state(), switchAfter=after_put(state(email_on=True)),
                  actions=[{"do": "check", "sel": "[data-hook='alerts-email-toggle']", "capture": [
                      q("test", "[data-hook='alerts-email-test']", "exists"), q("note", "[data-hook='alerts-email-note']")]}])
        self.assertEqual(puts(on)[0]["body"], {"channels": {"email": True}})
        self.assertTrue(on["captures"]["0"]["test"])
        self.assertEqual(on["captures"]["0"]["note"], "On.")
        off = page(state(email_on=True), switchAfter=after_put(state()),
                   actions=[{"do": "check", "checked": False, "sel": "[data-hook='alerts-email-toggle']", "capture": [
                       q("test", "[data-hook='alerts-email-test']", "exists"), q("note", "[data-hook='alerts-email-note']")]}])
        self.assertEqual(puts(off)[0]["body"], {"channels": {"email": False}})
        self.assertFalse(off["captures"]["0"]["test"])
        self.assertEqual(off["captures"]["0"]["note"], "Off.")

    def test_a_test_button_sends_the_same_request_as_before_and_says_what_came_back(self):
        out = page(state(email_on=True, push_on=True), routes={"POST /me/alerts/test": [200, {"ok": True, "message": "Test email sent."}]},
                   actions=[{"do": "click", "sel": "[data-hook='alerts-email-test']"},
                            {"do": "click", "sel": "[data-hook='alerts-push-test']"}],
                   queries=[q("status", "[data-hook='alerts-status']")])
        tests = [p for p in out["posts"] if p["url"] == "/me/alerts/test"]
        self.assertEqual([t["body"] for t in tests], [{"channel": "email"}, {"channel": "push"}])
        self.assertEqual(out["final"]["status"], "Test email sent.")


@unittest.skipUnless(HAS_NODE, "node is not installed")
class AToggleChangesOneRowInPlace(unittest.TestCase):
    MARKS = [{"do": "mark", "sel": "[data-hook='alerts-body']", "wait": 0}, {"do": "mark", "sel": ".alerts__row", "wait": 0},
             {"do": "mark", "sel": "input[role='switch']", "wait": 0}, {"do": "mark", "sel": ".alerts__list", "wait": 0},
             {"do": "mark", "sel": "[data-hook='alerts-feed'] button", "wait": 0}]

    def untouched(self):
        return [q("body", "[data-hook='alerts-body'][data-mark='m']", "count"),
                q("rows", ".alerts__row[data-mark='m']", "count"), q("allRows", ".alerts__row", "count"),
                q("switches", "input[role='switch'][data-mark='m']", "count"), q("allSwitches", "input[role='switch']", "count"),
                q("lists", ".alerts__list[data-mark='m']", "count"), q("allLists", ".alerts__list", "count"),
                q("feedButtons", "[data-hook='alerts-feed'] button[data-mark='m']", "count")]

    def assert_nothing_rebuilt(self, f):
        self.assertEqual(f["body"], 1, "the panel body was torn down and rebuilt")
        self.assertEqual(f["rows"], f["allRows"], "a row was replaced by a new one")
        self.assertEqual(f["switches"], f["allSwitches"], "a switch was replaced by a new one (focus and scroll are lost)")
        self.assertEqual(f["lists"], f["allLists"])
        self.assertEqual(f["feedButtons"], 1)

    def test_a_channel_switch_keeps_every_node(self):
        out = page(state(), switchAfter=after_put(state(email_on=True)), actions=self.MARKS + [
            {"do": "check", "sel": "[data-hook='alerts-email-toggle']", "label": "toggle", "capture": self.untouched() + [
                q("on", "[data-hook='alerts-email-toggle']", "checked")]}])
        f = out["captures"]["toggle"]
        self.assert_nothing_rebuilt(f)
        self.assertTrue(f["on"])
        self.assertEqual(puts(out)[0]["body"], {"channels": {"email": True}})
        self.assertEqual(len(puts(out)), 1)

    def test_an_alert_type_switch_keeps_every_node_and_sends_the_same_request(self):
        out = page(state(), switchAfter=after_put(state(toggles={"live": True})), actions=self.MARKS + [
            {"do": "check", "sel": "[data-hook='alerts-event-live-toggle']", "label": "toggle", "capture": self.untouched() + [
                q("on", "[data-hook='alerts-event-live-toggle']", "checked")]}])
        self.assert_nothing_rebuilt(out["captures"]["toggle"])
        self.assertTrue(out["captures"]["toggle"]["on"])
        self.assertEqual([p["body"] for p in puts(out)], [{"event_toggles": {"live": True}}])

    def test_the_morning_switch_keeps_every_node_and_sends_the_same_request(self):
        out = page(state(), switchAfter=after_put(state(morning=False)), actions=self.MARKS + [
            {"do": "check", "checked": False, "sel": "[data-hook='alerts-morning-toggle']", "label": "toggle", "capture": self.untouched() + [
                q("on", "[data-hook='alerts-morning-toggle']", "checked")]}])
        self.assert_nothing_rebuilt(out["captures"]["toggle"])
        self.assertFalse(out["captures"]["toggle"]["on"])
        self.assertEqual([p["body"] for p in puts(out)], [{"morning_lineup": False}])

    def test_quiet_hours_save_only_as_a_pair_and_keep_every_node(self):
        out = page(state(), switchAfter=after_put(state(quiet=(22, 6))), actions=self.MARKS + [
            {"do": "set", "sel": "[data-hook='alerts-quiet'] select", "index": 0, "value": "22", "wait": 0},
            {"do": "check", "sel": "[data-hook='alerts-quiet'] select", "index": 0, "label": "half", "capture": [
                q("status", "[data-hook='alerts-status']")]},
            {"do": "set", "sel": "[data-hook='alerts-quiet'] select", "index": 1, "value": "6", "wait": 0},
            {"do": "check", "sel": "[data-hook='alerts-quiet'] select", "index": 1, "label": "pair", "capture": self.untouched() + [
                q("start", "[data-hook='alerts-quiet'] select", "value")]}])
        self.assertEqual(out["captures"]["half"]["status"], "", "half a pair says nothing and saves nothing")
        self.assertEqual([p["body"] for p in puts(out)], [{"quiet_start": 22, "quiet_end": 6}])
        self.assert_nothing_rebuilt(out["captures"]["pair"])
        self.assertEqual(out["captures"]["pair"]["start"], "22")

    def test_a_failed_save_puts_the_switch_back_in_the_same_node(self):
        out = page(state(), routes={"PUT /me/alerts": [500, {"detail": "boom"}]}, actions=self.MARKS + [
            {"do": "check", "sel": "[data-hook='alerts-event-live-toggle']", "label": "toggle", "capture": self.untouched() + [
                q("on", "[data-hook='alerts-event-live-toggle']", "checked"), q("status", "[data-hook='alerts-status']"),
                q("bad", "[data-hook='alerts-status']", "attr", "data-bad")]}])
        f = out["captures"]["toggle"]
        self.assert_nothing_rebuilt(f)
        self.assertFalse(f["on"], "the server said no, so the switch is off again")
        self.assertEqual(f["status"], "That did not work. Try again in a minute.")
        self.assertEqual(f["bad"], "true")

    def test_the_phone_browser_that_cannot_push_says_so_and_nothing_moves(self):
        out = page(state(), actions=self.MARKS + [
            {"do": "check", "sel": "[data-hook='alerts-push-toggle']", "label": "toggle", "capture": self.untouched() + [
                q("on", "[data-hook='alerts-push-toggle']", "checked"), q("status", "[data-hook='alerts-status']")]}])
        f = out["captures"]["toggle"]
        self.assert_nothing_rebuilt(f)
        self.assertFalse(f["on"])
        self.assertEqual(f["status"], "This browser cannot show push notifications.")
        self.assertEqual(puts(out), [], "a switch that could not be turned on sends nothing")

    def test_a_typed_phone_number_survives_another_switch(self):
        out = page(state(sms="new"), switchAfter=after_put(state(sms="new", email_on=True)), actions=[
            {"do": "set", "sel": "[data-hook='alerts-sms-phone']", "value": "5550142233"},
            {"do": "check", "sel": "[data-hook='alerts-sms-agree']"},
            {"do": "check", "sel": "[data-hook='alerts-email-toggle']", "label": "toggle", "capture": [
                q("phone", "[data-hook='alerts-sms-phone']", "value"), q("agree", "[data-hook='alerts-sms-agree']", "checked"),
                q("email", "[data-hook='alerts-email-toggle']", "checked")]}])
        f = out["captures"]["toggle"]
        self.assertEqual(f["phone"], "5550142233")
        self.assertTrue(f["agree"])
        self.assertTrue(f["email"])

    def test_a_failed_text_request_keeps_what_was_typed(self):
        out = page(state(sms="new"), routes={"POST /me/alerts/sms": [429, {"detail": {"message": "Try again later."}}]}, actions=[
            {"do": "set", "sel": "[data-hook='alerts-sms-phone']", "value": "5550142233"},
            {"do": "check", "sel": "[data-hook='alerts-sms-agree']"},
            {"do": "click", "sel": "[data-hook='alerts-sms-form'] button", "label": "send", "capture": [
                q("phone", "[data-hook='alerts-sms-phone']", "value"), q("agree", "[data-hook='alerts-sms-agree']", "checked"),
                q("status", "[data-hook='alerts-status']")]}])
        self.assertEqual([p["body"] for p in out["posts"] if p["url"] == "/me/alerts/sms"], [{"phone": "5550142233", "consent": True}])
        f = out["captures"]["send"]
        self.assertEqual((f["phone"], f["agree"]), ("5550142233", True))
        self.assertEqual(f["status"], "Try again later.")

    def test_the_code_step_replaces_only_the_form(self):
        out = page(state(sms="new"), routes={"POST /me/alerts/sms": [200, state(sms="pending")]}, actions=[
            {"do": "mark", "sel": "[data-hook='alerts-sms']", "wait": 0}, {"do": "mark", "sel": "[data-hook='alerts-email']", "wait": 0},
            {"do": "set", "sel": "[data-hook='alerts-sms-phone']", "value": "5550142233", "wait": 0},
            {"do": "click", "sel": "[data-hook='alerts-sms-form'] button", "label": "sent", "capture": [
                q("rows", ".alerts__row[data-mark='m']", "count"), q("code", "[data-hook='alerts-sms-code']", "exists"),
                q("phone", "[data-hook='alerts-sms-phone']", "exists"), q("note", "[data-hook='alerts-sms-note']"),
                q("status", "[data-hook='alerts-status']")]}])
        f = out["captures"]["sent"]
        self.assertEqual(f["rows"], 2)
        self.assertTrue(f["code"])
        self.assertFalse(f["phone"])
        self.assertEqual(f["note"], "Type the code we texted you below.")
        self.assertEqual(f["status"], "Code sent. Type it below.")

    def test_the_saved_message_goes_by_itself_and_an_error_stays(self):
        ok = page(state(), switchAfter=after_put(state(toggles={"live": True})), actions=[
            {"do": "check", "sel": "[data-hook='alerts-event-live-toggle']", "label": "now", "wait": 40,
             "capture": [q("status", "[data-hook='alerts-status']")]},
            {"do": "key", "sel": "[data-hook='alerts-status']", "key": "x", "label": "later", "wait": 4200,
             "capture": [q("status", "[data-hook='alerts-status']")]}])
        self.assertEqual(ok["captures"]["now"]["status"], "Saved.")
        self.assertEqual(ok["captures"]["later"]["status"], "", "a sticky 'Saved.' would sit over the page for good")
        bad = page(state(), routes={"PUT /me/alerts": [500, {"detail": "boom"}]}, actions=[
            {"do": "check", "sel": "[data-hook='alerts-event-live-toggle']", "wait": 4200,
             "label": "later", "capture": [q("status", "[data-hook='alerts-status']")]}])
        self.assertEqual(bad["captures"]["later"]["status"], "That did not work. Try again in a minute.")


@unittest.skipUnless(HAS_NODE, "node is not installed")
class ThePrivateFeed(unittest.TestCase):
    ROTATED = {**state(feed_set=True), "feed_url_once": "https://linehound.test/alerts/feed/SECRET.xml"}

    def test_a_member_without_a_link_gets_one_button(self):
        out = page(state(), queries=[q("buttons", "[data-hook='alerts-feed'] button", "texts"), q("title", "[data-hook='alerts-feed'] .alerts__label"),
                                     q("url", "[data-hook='alerts-feed-url']", "exists")])
        self.assertEqual(out["final"]["buttons"], ["Make my feed link"])
        self.assertEqual(out["final"]["title"], "Private alert feed")
        self.assertFalse(out["final"]["url"])

    def test_the_link_is_shown_once_with_copy_and_reset_together_on_the_line_beneath(self):
        out = page(state(), routes={"POST /me/alerts/feed/rotate": [200, self.ROTATED]},
                   actions=[{"do": "click", "sel": "[data-hook='alerts-feed-reset']", "label": "made", "capture": [
                       q("url", "[data-hook='alerts-feed-url']", "value"), q("readonly", "[data-hook='alerts-feed-url']", "attr", "readonly"),
                       q("urlClass", "[data-hook='alerts-feed-url']", "attr", "class"),
                       q("inActions", "[data-hook='alerts-feed'] .alerts__actions [data-hook='alerts-feed-url']", "exists"),
                       q("line", "[data-hook='alerts-feed'] .alerts__actions button", "texts"),
                       q("hooks", "[data-hook='alerts-feed'] .alerts__actions button", "attrs", "data-hook"),
                       q("status", "[data-hook='alerts-status']"), q("once", "[data-hook='alerts-feed']")]},
                            {"do": "click", "sel": "[data-hook='alerts-feed-copy']", "label": "copied", "capture": [
                                q("status", "[data-hook='alerts-status']")]}])
        f = out["captures"]["made"]
        self.assertEqual(f["url"], "https://linehound.test/alerts/feed/SECRET.xml")
        self.assertEqual(f["readonly"], "readonly")
        self.assertIn("alerts__link", f["urlClass"])
        self.assertFalse(f["inActions"], "the link box has its own full-width line")
        self.assertEqual(f["line"], ["Copy feed link", "Reset link"])
        self.assertEqual(f["hooks"], ["alerts-feed-copy", "alerts-feed-reset"])
        self.assertEqual(f["status"], "Feed link made. Copy it now.")
        self.assertIn("This is the only time the link is shown. Copy it now.", f["once"])
        self.assertEqual(out["clipboard"], ["https://linehound.test/alerts/feed/SECRET.xml"])
        self.assertEqual(out["captures"]["copied"]["status"], "Feed link copied.")
        self.assertEqual([p["url"] for p in out["posts"]], ["/me/alerts/feed/rotate"])

    def test_a_link_that_is_set_is_not_shown_again_and_reset_still_works(self):
        out = page(state(feed_set=True), routes={"POST /me/alerts/feed/rotate": [200, self.ROTATED]},
                   captureInitial=[q("set", "[data-hook='alerts-feed-set']"), q("url", "[data-hook='alerts-feed-url']", "exists"),
                                   q("buttons", "[data-hook='alerts-feed'] button", "texts")],
                   actions=[{"do": "click", "sel": "[data-hook='alerts-feed-reset']", "label": "reset", "capture": [
                       q("status", "[data-hook='alerts-status']"), q("url", "[data-hook='alerts-feed-url']", "value")]}])
        first = out["captures"]["initial"]
        self.assertEqual(first["set"], "Your feed link is set. It is not shown again.")
        self.assertFalse(first["url"])
        self.assertEqual(first["buttons"], ["Reset link"])
        self.assertEqual(out["captures"]["reset"]["status"], "New link made. The old one stopped working.")
        self.assertEqual(out["captures"]["reset"]["url"], "https://linehound.test/alerts/feed/SECRET.xml")

    def test_a_free_member_is_told_why_there_is_no_feed(self):
        out = page(state(feed_allowed=False), queries=[q("paid", "[data-hook='alerts-feed-paid']"),
                                                       q("buttons", "[data-hook='alerts-feed'] button", "count")])
        self.assertEqual(out["final"]["paid"], "The private text feed is part of the member plan. Email and browser notifications are free.")
        self.assertEqual(out["final"]["buttons"], 0)

    def test_copying_without_clipboard_access_selects_the_link_and_says_so(self):
        out = page(state(), noClipboard=True, routes={"POST /me/alerts/feed/rotate": [200, self.ROTATED]},
                   actions=[{"do": "click", "sel": "[data-hook='alerts-feed-reset']"},
                            {"do": "click", "sel": "[data-hook='alerts-feed-copy']"}],
                   queries=[q("status", "[data-hook='alerts-status']"), q("bad", "[data-hook='alerts-status']", "attr", "data-bad")])
        self.assertEqual(out["final"]["status"], "Select the link and copy it.")
        self.assertEqual(out["final"]["bad"], "true")


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheFirstLoad(unittest.TestCase):
    HOOKS = ("account-alerts", "alerts-body", "alerts-status", "alerts-email", "alerts-email-toggle", "alerts-email-note",
             "alerts-push", "alerts-push-toggle", "alerts-push-note", "alerts-ios-note", "alerts-events",
             "alerts-morning", "alerts-morning-toggle", "alerts-event-placed", "alerts-event-placed-toggle",
             "alerts-event-starting-toggle", "alerts-event-live-toggle", "alerts-event-settled-toggle", "alerts-quiet",
             "alerts-feed", "alerts-feed-reset")

    def test_every_hook_the_page_had_is_still_there(self):
        hooks = page(state())["hooks"]
        for hook in self.HOOKS:
            self.assertIn(hook, hooks)

    def test_the_status_line_is_a_live_region_and_starts_empty(self):
        out = page(state(), queries=[q("role", "[data-hook='alerts-status']", "attr", "role"),
                                     q("text", "[data-hook='alerts-status']")])
        self.assertEqual(out["final"]["role"], "status")
        self.assertEqual(out["final"]["text"], "")

    def test_a_failed_load_shows_nothing_rather_than_half_a_page(self):
        out = run_page("alerts", routes={"/me/alerts": [500, {"detail": "down"}]}, stored=SEEN_ZONE,
                       queries=[q("rows", ".alerts__row", "count"), q("status", "[data-hook='alerts-status']")])
        self.assertEqual(out["final"]["rows"], 0)
        self.assertEqual(out["final"]["status"], "That did not work. Try again in a minute.")

    def test_the_browser_zone_is_still_sent_once_on_the_first_visit(self):
        out = run_page("alerts", routes={"/me/alerts": [200, state()], "PUT /me/alerts": [200, state()]}, tz="Asia/Tokyo")
        sent = [p["body"] for p in puts(out)]
        self.assertEqual(sent, [{"tz": "Asia/Tokyo"}])


class TheStylesheet(unittest.TestCase):
    """The panel shipped with no CSS at all. Every class the script draws needs a rule, in the sheet the account page loads."""
    CSS = (WEB / "css" / "signin.css").read_text(encoding="utf-8")
    JS = (WEB / "js" / "alerts.js").read_text(encoding="utf-8")

    def test_every_class_the_script_draws_has_a_rule(self):
        used = set(re.findall(r"\balerts__[a-z-]+", self.JS))
        self.assertTrue({"alerts__row", "alerts__label", "alerts__switch", "alerts__note", "alerts__actions"} <= used)
        for name in sorted(used):
            self.assertRegex(self.CSS, rf"\.{name}\b", f".{name} is drawn by alerts.js and styled nowhere")

    def test_the_switch_is_drawn_by_the_stylesheet_and_is_a_phone_sized_target(self):
        rule = re.search(r"\.signin \.alerts__switch\s*\{([^}]*)\}", self.CSS).group(1)
        self.assertIn("appearance: none", rule)
        self.assertRegex(rule, r"width:\s*(5\d|6\d)px")
        self.assertRegex(self.CSS, r"\.signin \.alerts__switch:checked")
        self.assertRegex(self.CSS, r"\.signin \.alerts__switch:focus-visible")
        self.assertRegex(self.CSS, r"\.signin \.alerts__switch:disabled")
        self.assertIn("prefers-reduced-motion", self.CSS)
        line = re.search(r"\.signin \.alerts__line\s*\{([^}]*)\}", self.CSS).group(1)
        self.assertRegex(line, r"min-height:\s*4[4-9]px")

    def test_form_fields_do_not_trigger_the_iphone_zoom(self):
        rule = re.search(r"\.signin \.alerts__field\s*,?[^{]*\{([^}]*)\}", self.CSS).group(1)
        self.assertRegex(rule, r"font-size:\s*16px")

    def test_the_account_page_mounts_the_panel_once(self):
        signin = (WEB / "js" / "signin.js").read_text(encoding="utf-8")
        self.assertEqual(signin.count("alertsPanel()"), 1)
        self.assertEqual(signin.count('import { alertsPanel } from "./alerts.js";'), 1)

    def test_nothing_rebuilds_the_whole_panel_on_a_toggle(self):
        """The cause of the glitch, pinned in the source: the only whole-panel clear is the build, never a save."""
        save = re.search(r"async function put\(.*?\n  }\n", self.JS, re.S)
        self.assertIsNotNone(save, "the save function moved; update this check")
        self.assertNotIn("render()", save.group(0))
        self.assertNotIn("clear(body)", save.group(0))


if __name__ == "__main__":
    unittest.main()
