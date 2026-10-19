"""The admin dashboard (web/admin.html), run for real under node against a fake DOM built from the page's
own HTML (tests/hounds_web_harness.mjs), with payloads in the shapes api/admin.py sends
(tests/admin_dashboard_fixtures.py).

Owner request, 2026-10-19: the admin page "needs UI and an actual html page and easy to use admin
privileges". What this file pins:

  * the token gate: the sign-in card is all that shows without a saved token or after a 401, a 404 says the
    admin surface is off (a different problem), the token is sent only as a header, saved in session storage
    and never shown back or put in an address;
  * the Overview: the KPI cards from the API's numbers (and an em dash where a source failed), the needs-
    attention list, the daily chart;
  * People: one filterable table, a row menu whose every item sends the right request with the typed reason
    (and sends nothing when the reason is empty), the server's refusal shown in its own words;
  * the access token: shown ONCE in a dialog with copy buttons, the sign-in link and a message to send, and
    gone from the page when the dialog closes;
  * Funnel, Health (tones by age, reasons verbatim) and Support.

The classic section renderers still in web/js/admin.js keep their own tests (test_admin_testers_page.py,
test_admin_free_members_page.py, test_admin_funnel_by_source.py). Skipped when node is not installed.
"""

from __future__ import annotations

import copy
import json
import re
import unittest
from datetime import datetime, timedelta, timezone

from tests import admin_dashboard_fixtures as F
from tests.hounds_web_runner import HAS_NODE, WEB, run_js, run_page

NOW = datetime(2026, 10, 19, 14, 0, 0, tzinfo=timezone.utc)
TOKEN_KEY = "aisportsanalysis.admin_token"
ADMIN_TOKEN = "tok-admin-123"
STORED = {TOKEN_KEY: ADMIN_TOKEN}
ISSUED = F.ISSUED_TOKEN


def routes(**over):
    """GET fixtures as harness routes, plus overrides keyed by full route key."""
    table = {path: [200, body] for path, body in F.build(NOW).items()}
    table.update(over)
    return table


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def run(**scenario):
    scenario.setdefault("now", NOW.isoformat())
    scenario.setdefault("routes", routes())
    scenario.setdefault("stored", dict(STORED))
    return run_page("admin", **scenario)


def row_sel(user_id, hook):
    return f"[data-hook='admin-person-row'][data-user-id='{user_id}'] [data-hook='{hook}']"


def menu_steps(user_id, action):
    """Open a person's row menu and press one of its items."""
    return [
        dict(do="click", sel=row_sel(user_id, "admin-row-menu")),
        dict(do="click", sel=f"[data-hook='admin-menu-item'][data-action='{action}']"),
    ]


def go(route):
    return dict(do="click", sel=f"[data-hook='admin-nav-item'][data-route='{route}']")


def all_unauthorized():
    return {f"{p}": [401, {"detail": {"error": "unauthorized", "message": "bad admin token"}}]
            for p in F.build(NOW)}


def nav_to_people(*steps):
    return [go("people"), *steps]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheTokenGate(unittest.TestCase):
    def test_without_a_saved_token_only_the_sign_in_card_shows_and_nothing_is_fetched(self):
        out = run(stored={}, queries=[
            q("gate", "[data-hook='admin-gate']", "hidden"),
            q("shell", "[data-hook='admin-shell']", "hidden"),
            q("chip", "[data-hook='admin-token-chip']"),
            q("signout", "[data-hook='admin-signout']", "hidden"),
            q("field", "[data-hook='admin-token-input']", "value"),
            q("fieldType", "[data-hook='admin-token-input']", "attr", attr="type"),
        ])
        f = out["final"]
        self.assertEqual((f["gate"], f["shell"], f["signout"]), (False, True, True))
        self.assertEqual(f["chip"], "Not signed in")
        self.assertEqual((f["field"], f["fieldType"]), ("", "password"))
        self.assertEqual(out["gets"], [])

    def test_an_empty_submit_asks_for_the_token_and_sends_nothing(self):
        out = run(stored={}, actions=[dict(do="submit", sel="[data-hook='admin-gate-form']")],
                  queries=[q("msg", "[data-hook='admin-gate-message']")])
        self.assertEqual(out["final"]["msg"], "Paste the admin token first.")
        self.assertEqual(out["gets"], [])

    def test_signing_in_saves_the_token_loads_the_data_and_keeps_it_out_of_every_address(self):
        out = run(stored={}, actions=[
            dict(do="set", sel="[data-hook='admin-token-input']", value=ADMIN_TOKEN),
            dict(do="submit", sel="[data-hook='admin-gate-form']"),
        ], queries=[
            q("gate", "[data-hook='admin-gate']", "hidden"),
            q("shell", "[data-hook='admin-shell']", "hidden"),
            q("chip", "[data-hook='admin-token-chip']"),
            q("field", "[data-hook='admin-token-input']", "value"),
            q("signout", "[data-hook='admin-signout']", "hidden"),
        ])
        f = out["final"]
        self.assertEqual((f["gate"], f["shell"], f["signout"]), (True, False, False))
        self.assertEqual(f["chip"], "Signed in")
        self.assertEqual(f["field"], "")
        self.assertEqual(out["storedAfter"].get(TOKEN_KEY), ADMIN_TOKEN)
        self.assertEqual(sorted(out["gets"]), sorted(F.build(NOW)))
        for call in out["getCalls"]:
            self.assertEqual(call["headers"].get("X-Admin-Token"), ADMIN_TOKEN)
            self.assertNotIn(ADMIN_TOKEN, call["url"])
            self.assertNotIn("Authorization", call["headers"])
        self.assertNotIn(ADMIN_TOKEN, out["text"])

    def test_a_saved_token_is_never_shown_back(self):
        out = run(queries=[q("field", "[data-hook='admin-token-input']", "value")])
        self.assertEqual(out["final"]["field"], "")
        self.assertNotIn(ADMIN_TOKEN, out["text"])
        self.assertNotIn(ADMIN_TOKEN, json.dumps(out["hooks"]))

    def test_a_401_shows_the_sign_in_card_and_forgets_the_rejected_token(self):
        out = run(routes=all_unauthorized(), queries=[
            q("gate", "[data-hook='admin-gate']", "hidden"),
            q("shell", "[data-hook='admin-shell']", "hidden"),
            q("msg", "[data-hook='admin-gate-message']"),
            q("chip", "[data-hook='admin-token-chip']"),
            q("field", "[data-hook='admin-token-input']", "value"),
        ])
        f = out["final"]
        self.assertEqual((f["gate"], f["shell"]), (False, True))
        self.assertIn("rejected", f["msg"])
        self.assertEqual(f["chip"], "Token rejected")
        self.assertEqual(f["field"], "")
        self.assertNotIn(TOKEN_KEY, out["storedAfter"])
        self.assertNotIn(ADMIN_TOKEN, out["text"])

    def test_a_404_says_the_admin_surface_is_off_and_is_not_a_wrong_token(self):
        gone = {p: [404, {"detail": "Not Found"}] for p in F.build(NOW)}
        out = run(routes=gone, queries=[
            q("gate", "[data-hook='admin-gate']", "hidden"),
            q("msg", "[data-hook='admin-gate-message']"),
            q("chip", "[data-hook='admin-token-chip']"),
        ])
        f = out["final"]
        self.assertFalse(f["gate"])
        self.assertIn("switched off", f["msg"])
        self.assertIn("APP_ADMIN_TOKEN", f["msg"])
        self.assertEqual(f["chip"], "Admin off")
        self.assertIn(TOKEN_KEY, out["storedAfter"])        # not a credential problem: nothing is forgotten

    def test_signing_out_clears_the_token_and_the_data(self):
        out = run(actions=[dict(do="click", sel="[data-hook='admin-signout']")], queries=[
            q("gate", "[data-hook='admin-gate']", "hidden"),
            q("shell", "[data-hook='admin-shell']", "hidden"),
            q("msg", "[data-hook='admin-gate-message']"),
            q("people", "[data-hook='admin-person-row']", "count"),
        ])
        f = out["final"]
        self.assertEqual((f["gate"], f["shell"]), (False, True))
        self.assertIn("signed out", f["msg"])
        self.assertNotIn(TOKEN_KEY, out["storedAfter"])


def expected_week(key_kinds):
    """The 7-day sum of `key_kinds` from the fixture's daily counts, ending the day of NOW."""
    daily = F.build(NOW)["/admin/overview"]["events"]["daily_counts_by_kind"]
    total = 0
    for i in range(7):
        day = (NOW - timedelta(days=i)).strftime("%Y-%m-%d")
        total += sum(daily.get(day, {}).get(kind, 0) for kind in key_kinds)
    return total


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheOverview(unittest.TestCase):
    def kpi_values(self, **over):
        keys = ["total", "waitlist", "testers", "free", "paying", "signups", "visits"]
        out = run(queries=[q(k, f"[data-kpi='{k}'] [data-hook='admin-kpi-value']") for k in keys], **over)
        return out, {k: out["final"][k] for k in keys}

    def test_kpi_cards_show_the_apis_numbers(self):
        _, values = self.kpi_values()
        self.assertEqual(values["total"], "14")
        self.assertEqual(values["waitlist"], "5")
        self.assertEqual(values["testers"], "2/20")             # two running, the third ended two days ago
        self.assertEqual(values["free"], "1")
        self.assertEqual(values["paying"], "1")
        self.assertEqual(values["signups"], str(expected_week(["account_created"])))
        self.assertEqual(values["visits"], str(expected_week(["landing_view", "public_page_view"])))
        self.assertGreater(int(values["visits"]), 0)

    def test_a_source_that_failed_is_a_dash_never_a_zero(self):
        table = routes()
        table["/admin/revenue"] = [503, {"detail": "down"}]
        table["/admin/comps"] = [503, {"detail": "down"}]
        out, values = self.kpi_values(routes=table)
        self.assertEqual((values["paying"], values["free"]), ("—", "—"))
        self.assertEqual(values["total"], "14")
        sub = run(routes=table, queries=[q("sub", "[data-kpi='paying']")])["final"]["sub"]
        self.assertIn("unavailable", sub)

    def test_the_chart_has_a_bar_for_every_day_of_the_last_two_weeks_for_visits_and_signups(self):
        out = run(queries=[
            q("visitBars", "[data-chart='visits'] [data-hook='admin-chart-bar']", "count"),
            q("signupBars", "[data-chart='signups'] [data-hook='admin-chart-bar']", "count"),
            q("last", "[data-chart='visits'] [data-hook='admin-chart-bar']", "attrs", attr="data-day"),
            q("values", "[data-chart='signups'] [data-hook='admin-chart-bar']", "attrs", attr="data-value"),
        ])
        f = out["final"]
        self.assertEqual((f["visitBars"], f["signupBars"]), (14, 14))
        self.assertEqual(f["last"][-1], "2026-10-19")
        self.assertEqual(f["last"][0], "2026-10-06")
        self.assertEqual(sum(int(v) for v in f["values"]),
                         sum(F.build(NOW)["/admin/overview"]["events"]["daily_counts_by_kind"][d].get("account_created", 0)
                             for d in F.build(NOW)["/admin/overview"]["events"]["daily_counts_by_kind"]))

    def test_needs_your_attention_lists_the_waitlist_expiring_testers_stale_data_and_open_support(self):
        out = run(queries=[
            q("kinds", "[data-hook='admin-attention-item']", "attrs", attr="data-kind"),
            q("keys", "[data-hook='admin-attention-item']", "attrs", attr="data-key"),
            q("texts", "[data-hook='admin-attention-item']", "texts"),
        ])
        f = out["final"]
        keys = f["keys"]
        self.assertEqual(sorted(k for k in keys if k.startswith("approve-")),
                         ["approve-1", "approve-13", "approve-14", "approve-2", "approve-3"])
        self.assertEqual([k for k in keys if k.startswith("expiring-")], ["expiring-12"])     # 30h left; 5 days is not
        health = [k for k in keys if k.startswith("health-")]
        self.assertIn("health-prop_listing", health)
        self.assertIn("health-lineups_watch", health)
        self.assertIn("health-fresh_standings", health)
        self.assertIn("health-aging", health)
        self.assertIn("support-open", keys)
        joined = " ".join(f["texts"])
        self.assertIn("tim.tester@example.test", joined)
        self.assertIn("Lost my access code", joined)
        # red items first: a broken thing outranks a person waiting
        self.assertTrue(keys[0].startswith("health-") and keys[0] != "health-aging")

    def test_nothing_needs_you_says_so_instead_of_an_empty_box(self):
        table = {p: list(v) for p, v in routes().items()}
        quiet = copy.deepcopy(F.build(NOW))
        quiet["/admin/users"]["users"] = [u for u in quiet["/admin/users"]["users"]
                                          if u["status"] != "waitlisted" and not u["tester"]]
        quiet["/admin/testers"]["testers"] = []
        quiet["/admin/support"]["messages"] = []
        health = quiet["/admin/overview"]["store_health"]
        for name, check in health["forward_captures"].items():
            health["forward_captures"][name] = dict(check, status="ok", newest_row_age_seconds=600, reason=None, rows=5)
        health["data_freshness"]["stores"]["standings"] = {"through": "2026-10-18", "lag_days": 0, "stale": False, "reason": None}
        health["reasons"] = []
        health["checkout"] = {"status": "ok", "provider": "stripe", "mode": "test", "reason": None}
        for path, body in quiet.items():
            table[path] = [200, body]
        out = run(routes=table, queries=[q("empty", "[data-hook='admin-attention-empty']"),
                                         q("items", "[data-hook='admin-attention-item']", "count")])
        self.assertEqual(out["final"]["items"], 0)
        self.assertIn("Nothing needs you", out["final"]["empty"])

    def test_the_attention_list_can_approve_without_leaving_the_overview(self):
        out = run(actions=[
            dict(do="click", sel="[data-key='approve-14'] [data-hook='admin-attention-approve']"),
            dict(do="set", sel="[data-hook='admin-field-reason']", value="friend of the project"),
            dict(do="click", sel="[data-hook='admin-confirm-submit']"),
        ])
        post = out["posts"][0]
        self.assertEqual((post["url"], post["body"]), ("/admin/comps", {"user_id": 14, "reason": "friend of the project"}))


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePeopleTab(unittest.TestCase):
    def test_one_table_of_everyone_newest_first_with_a_status_word_each(self):
        out = run(actions=[go("people")], queries=[
            q("count", "[data-hook='admin-person-row']", "count"),
            q("emails", "[data-hook='admin-person-email']", "texts"),
            q("status", "[data-hook='admin-person-status']", "texts"),
            q("headers", "[data-hook='admin-people-table'] th", "texts"),
            q("summary", "[data-hook='admin-people-count']"),
            q("tim", row_sel(12, "admin-person-expiry")),
            q("wes", row_sel(14, "admin-person-expiry")),
        ])
        f = out["final"]
        self.assertEqual(f["count"], 14)
        self.assertEqual(f["emails"][0], "wes.waiting@example.test")                # joined five hours ago
        self.assertEqual(f["status"][:6], ["Waitlist", "Waitlist", "Pending payment", "Tester", "Tester", "Free member"])
        self.assertEqual(f["status"].count("Tester ended"), 1)
        self.assertEqual(f["status"].count("Paying"), 1)
        self.assertEqual(f["status"].count("Suspended"), 1)
        self.assertEqual(f["headers"][:6], ["Email", "Status", "Plan", "Joined", "Last seen", "Tester ends"])
        self.assertEqual(f["summary"], "14 people")
        self.assertEqual(f["tim"], "in 1d 6h")
        self.assertEqual(f["wes"], "—")

    def test_search_and_group_filters_narrow_the_list_and_say_how_many(self):
        out = run(actions=[
            go("people"),
            dict(do="set", sel="[data-hook='admin-people-search']", value="TESTER", capture=[
                q("emails", "[data-hook='admin-person-email']", "texts"),
                q("summary", "[data-hook='admin-people-count']")]),
            dict(do="set", sel="[data-hook='admin-people-search']", value="", capture=[]),
            dict(do="click", sel="[data-hook='admin-people-group'][data-group='waitlist']", capture=[
                q("n", "[data-hook='admin-person-row']", "count"),
                q("pressed", "[data-hook='admin-people-group'][data-group='waitlist']", "attr", attr="aria-pressed")]),
            dict(do="set", sel="[data-hook='admin-people-search']", value="no-such-person", capture=[
                q("empty", "[data-hook='admin-people-empty']")]),
        ])
        c = out["captures"]
        self.assertEqual(sorted(c["1"]["emails"]),
                         ["old.tester@example.test", "tess.tester@example.test", "tim.tester@example.test"])
        self.assertEqual(c["1"]["summary"], "3 of 14 people")
        self.assertEqual(c["3"]["n"], 5)
        self.assertEqual(c["3"]["pressed"], "true")
        self.assertIn("Nobody matches", c["4"]["empty"])

    def test_the_group_buttons_carry_their_counts(self):
        out = run(actions=[go("people")], queries=[
            q("groups", "[data-hook='admin-people-group']", "texts")])
        self.assertEqual(out["final"]["groups"],
                         ["All 14", "Waitlist 5", "Testers 3", "Free members 1", "Paying 1", "Suspended 1"])

    def test_the_menu_offers_only_what_applies_to_that_person(self):
        def items(user_id):
            out = run(actions=[go("people"), dict(do="click", sel=row_sel(user_id, "admin-row-menu"))], queries=[
                q("actions", "[data-hook='admin-menu-item']", "attrs", attr="data-action")])
            return out["final"]["actions"]
        self.assertEqual(items(14), ["approve", "grant", "password"])                           # waitlisted
        self.assertEqual(items(12), ["approve", "extend", "reissue", "password"])               # running tester
        self.assertEqual(items(9), ["reissue", "password", "revoke"])                           # free member
        self.assertEqual(items(6), ["password"])                                                # suspended
        self.assertEqual(items(7), ["reissue", "password"])                                     # paying: nothing to give

    def test_reset_password_is_a_disabled_placeholder_until_the_route_exists(self):
        out = run(actions=[go("people"), dict(do="click", sel=row_sel(12, "admin-row-menu"))], queries=[
            q("disabled", "[data-hook='admin-menu-item'][data-action='password']", "disabled"),
            q("note", "[data-hook='admin-menu-item'][data-action='password']")])
        self.assertTrue(out["final"]["disabled"])
        self.assertIn("Not available yet", out["final"]["note"])
        self.assertEqual(out["posts"], [])

    def test_rows_are_labelled_cells_so_the_table_becomes_cards_on_a_phone(self):
        out = run(actions=[go("people")], queries=[
            q("labels", "[data-hook='admin-person-row'] [data-label]", "attrs", attr="data-label")])
        labels = out["final"]["labels"][:7]
        self.assertEqual(labels, ["Email", "Status", "Plan", "Joined", "Last seen", "Tester ends", ""])
        css = (WEB / "css" / "admin.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 899px)", css)
        self.assertIn("attr(data-label)", css)


@unittest.skipUnless(HAS_NODE, "node not installed")
class RowActionsSendTheRightRequest(unittest.TestCase):
    """Each menu item opens a confirm dialog; where the API needs a reason the dialog will not send without one."""

    CASES = [
        # (name, user id, menu action, needs a reason, route key, expected body for reason "because")
        ("approve", 14, "approve", True, "POST /admin/comps", {"user_id": 14, "reason": "because"}),
        ("grant", 13, "grant", False, "POST /admin/testers", {"user_id": 13}),
        ("extend", 12, "extend", True, "POST /admin/testers/extend", {"user_id": 12, "reason": "because"}),
        ("reissue", 11, "reissue", True, "POST /admin/users/reissue", {"user_id": 11, "reason": "because"}),
        ("revoke", 9, "revoke", True, "POST /admin/comps/revoke", {"user_id": 9, "reason": "because"}),
    ]

    def answer(self, key, user_id):
        if key.endswith("/revoke"):
            return [200, {"ok": True}]
        kind = "comp" if key.endswith("/comps") else "tester"
        return [200, F.issued(f"user{user_id}@example.test", kind=kind)]

    def run_case(self, user_id, action, reason, key):
        steps = menu_steps(user_id, action)
        if reason is not None:
            steps.append(dict(do="set", sel="[data-hook='admin-field-reason']", value=reason))
        steps.append(dict(do="click", sel="[data-hook='admin-confirm-submit']"))
        table = routes(**{key: self.answer(key, user_id)})
        return run(routes=table, actions=nav_to_people(*steps), queries=[
            q("dialog", "[data-hook='admin-confirm']", "exists"),
            q("fieldError", "[data-hook='admin-field-error-reason']"),
            q("token", "[data-hook='admin-token-dialog']", "exists"),
        ])

    def test_every_action_posts_to_its_endpoint_with_the_typed_reason(self):
        for name, user_id, action, needs_reason, key, body in self.CASES:
            with self.subTest(action=name):
                out = self.run_case(user_id, action, "because" if needs_reason else None, key)
                posts = out["posts"]
                self.assertEqual(len(posts), 1)
                self.assertEqual("POST " + posts[0]["url"], key)
                self.assertEqual(posts[0]["body"], body)
                self.assertEqual(posts[0]["headers"].get("X-Admin-Token"), ADMIN_TOKEN)
                self.assertFalse(out["final"]["dialog"])             # the confirm dialog closed on success

    def test_an_empty_reason_sends_nothing_and_says_which_field(self):
        for name, user_id, action, needs_reason, key, body in self.CASES:
            if not needs_reason:
                continue
            for typed in (None, "   "):
                with self.subTest(action=name, typed=typed):
                    out = self.run_case(user_id, action, typed, key)
                    self.assertEqual(out["posts"], [])
                    self.assertTrue(out["final"]["dialog"])           # still open
                    self.assertIn("Required", out["final"]["fieldError"])

    def test_the_actions_that_issue_a_code_show_it_and_revoke_shows_none(self):
        for name, user_id, action, needs_reason, key, body in self.CASES:
            with self.subTest(action=name):
                out = self.run_case(user_id, action, "because" if needs_reason else None, key)
                self.assertEqual(out["final"]["token"], name != "revoke")

    def test_the_data_is_re_read_after_an_action_so_the_table_is_current(self):
        out = self.run_case(14, "approve", "because", "POST /admin/comps")
        self.assertEqual(out["gets"].count("/admin/users"), 2)

    def test_the_server_refusal_is_shown_in_its_own_words_and_no_token_appears(self):
        refusal = {"detail": {"error": "has_subscription", "message": "this person already has a subscription"}}
        out = run(routes=routes(**{"POST /admin/comps": [409, refusal]}),
                  actions=nav_to_people(*menu_steps(14, "approve"),
                                        dict(do="set", sel="[data-hook='admin-field-reason']", value="because"),
                                        dict(do="click", sel="[data-hook='admin-confirm-submit']")),
                  queries=[q("status", "[data-hook='admin-dialog-status']"),
                           q("dialog", "[data-hook='admin-confirm']", "exists"),
                           q("token", "[data-hook='admin-token-dialog']", "exists"),
                           q("again", "[data-hook='admin-confirm-submit']", "disabled")])
        f = out["final"]
        self.assertEqual(f["status"], "this person already has a subscription")
        self.assertTrue(f["dialog"])
        self.assertFalse(f["token"])
        self.assertFalse(f["again"])                                   # can be pressed again after reading it
        self.assertNotIn(ISSUED, out["text"])

    def test_a_401_during_an_action_returns_to_the_sign_in_card(self):
        out = run(routes=routes(**{"POST /admin/comps": [401, {"detail": {"error": "unauthorized"}}]}),
                  actions=nav_to_people(*menu_steps(14, "approve"),
                                        dict(do="set", sel="[data-hook='admin-field-reason']", value="because"),
                                        dict(do="click", sel="[data-hook='admin-confirm-submit']")),
                  queries=[q("gate", "[data-hook='admin-gate']", "hidden"),
                           q("shell", "[data-hook='admin-shell']", "hidden"),
                           q("dialog", "[data-hook='admin-confirm']", "exists"),
                           q("msg", "[data-hook='admin-gate-message']")])
        f = out["final"]
        self.assertEqual((f["gate"], f["shell"], f["dialog"]), (False, True, False))
        self.assertIn("rejected", f["msg"])
        self.assertNotIn(TOKEN_KEY, out["storedAfter"])

    def test_add_person_grants_a_tester_by_email_or_free_access_with_a_reason(self):
        add = [go("people"), dict(do="click", sel="[data-hook='admin-add-person']"),
               dict(do="set", sel="[data-hook='admin-field-email']", value="new.person@example.test")]
        free_no_reason = run(actions=add + [dict(do="click", sel="[data-hook='admin-add-free']")],
                             queries=[q("err", "[data-hook='admin-field-error-reason']")])
        self.assertEqual(free_no_reason["posts"], [])
        self.assertIn("Required", free_no_reason["final"]["err"])

        tester = run(routes=routes(**{"POST /admin/testers": [200, F.issued("new.person@example.test")]}),
                     actions=add + [dict(do="click", sel="[data-hook='admin-add-tester']")])
        self.assertEqual([(p["url"], p["body"]) for p in tester["posts"]],
                         [("/admin/testers", {"email": "new.person@example.test"})])

        free = run(routes=routes(**{"POST /admin/comps": [200, F.issued("new.person@example.test", kind="comp")]}),
                   actions=add + [dict(do="set", sel="[data-hook='admin-field-reason']", value="press contact"),
                                  dict(do="click", sel="[data-hook='admin-add-free']")])
        self.assertEqual([(p["url"], p["body"]) for p in free["posts"]],
                         [("/admin/comps", {"email": "new.person@example.test", "reason": "press contact"})])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheAccessTokenIsShownOnce(unittest.TestCase):
    def approve(self, *more, **scenario):
        steps = nav_to_people(
            *menu_steps(14, "approve"),
            dict(do="set", sel="[data-hook='admin-field-reason']", value="because"),
            dict(do="click", sel="[data-hook='admin-confirm-submit']"),
            *more)
        table = routes(**{"POST /admin/comps": [200, F.issued("wes.waiting@example.test", kind="comp")]})
        return run(routes=table, actions=steps, **scenario)

    def test_the_dialog_has_the_code_the_link_the_message_and_the_warning(self):
        out = self.approve(queries=[
            q("dialog", "[data-hook='admin-token-dialog']", "exists"),
            q("title", "[data-hook='admin-token-dialog'] h2"),
            q("code", "[data-hook='admin-token-value']", "value"),
            q("readonly", "[data-hook='admin-token-value']", "attr", attr="readonly"),
            q("link", "[data-hook='admin-token-link']", "attr", attr="href"),
            q("message", "[data-hook='admin-token-message']", "value"),
            q("warning", "[data-hook='admin-token-warning']"),
            q("summary", "[data-hook='admin-token-summary']"),
            q("copy", "[data-hook='admin-token-copy']"),
        ])
        f = out["final"]
        self.assertTrue(f["dialog"])
        self.assertIn("wes.waiting@example.test", f["title"])
        self.assertEqual(f["code"], ISSUED)
        self.assertIsNotNone(f["readonly"])
        self.assertTrue(f["link"].endswith("index.html#/signin"))
        self.assertNotIn(ISSUED, f["link"])                                   # the address holds no secret
        self.assertIn("Here's your LineHound access: open " + f["link"] + " and paste this code", f["message"])
        self.assertIn(ISSUED, f["message"])
        self.assertIn("Shown once", f["warning"])
        self.assertIn("cannot be shown again", f["warning"])
        self.assertIn("does not expire", f["summary"])
        self.assertEqual(f["copy"], "Copy code")

    def test_the_copy_buttons_copy_the_code_and_the_message(self):
        out = self.approve(
            dict(do="click", sel="[data-hook='admin-token-copy']", capture=[q("label", "[data-hook='admin-token-copy']")]),
            dict(do="click", sel="[data-hook='admin-token-copy-message']",
                 capture=[q("label", "[data-hook='admin-token-copy-message']")]))
        self.assertEqual(out["clipboard"][0], ISSUED)
        self.assertIn(ISSUED, out["clipboard"][1])
        self.assertTrue(out["clipboard"][1].startswith("Here's your LineHound access: open "))
        self.assertEqual(out["captures"]["5"]["label"], "Copied")
        self.assertEqual(out["captures"]["6"]["label"], "Message copied")

    def test_closing_the_dialog_removes_the_code_from_the_page_for_good(self):
        out = self.approve(dict(do="click", sel="[data-hook='admin-token-close']"), queries=[
            q("dialog", "[data-hook='admin-token-dialog']", "exists"),
            q("code", "[data-hook='admin-token-value']", "exists"),
            q("message", "[data-hook='admin-token-message']", "exists"),
        ])
        f = out["final"]
        self.assertEqual((f["dialog"], f["code"], f["message"]), (False, False, False))
        self.assertNotIn(ISSUED, out["text"])
        # never stored, never in an address, never asked for again
        self.assertNotIn(ISSUED, json.dumps(out["storedAfter"]))
        self.assertNotIn(ISSUED, json.dumps(out["gets"]))
        self.assertEqual([p["url"] for p in out["posts"]], ["/admin/comps"])
        self.assertNotIn(ISSUED, json.dumps([p["url"] for p in out["posts"]]))

    def test_a_click_outside_does_not_lose_the_code(self):
        out = self.approve(dict(do="click", sel="[data-hook='admin-backdrop']"),
                           queries=[q("dialog", "[data-hook='admin-token-dialog']", "exists")])
        self.assertTrue(out["final"]["dialog"])

    def test_the_page_behind_is_inert_while_the_dialog_is_open(self):
        out = self.approve(queries=[q("shell", "[data-hook='admin-shell']", "attr", attr="inert"),
                                    q("top", "[data-hook='admin-header']", "attr", attr="inert")])
        self.assertEqual(out["final"]["shell"], "")
        self.assertEqual(out["final"]["top"], "")
        closed = self.approve(dict(do="click", sel="[data-hook='admin-token-close']"),
                              queries=[q("shell", "[data-hook='admin-shell']", "attr", attr="inert")])
        self.assertIsNone(closed["final"]["shell"])

    def test_a_tester_code_says_when_it_ends(self):
        steps = nav_to_people(*menu_steps(13, "grant"), dict(do="click", sel="[data-hook='admin-confirm-submit']"))
        ends = (NOW + timedelta(days=7)).replace(microsecond=0).isoformat()
        out = run(routes=routes(**{"POST /admin/testers": [200, F.issued("nora.next@example.test", expires=ends)]}),
                  actions=steps, queries=[q("summary", "[data-hook='admin-token-summary']"),
                                          q("message", "[data-hook='admin-token-message']", "value")])
        self.assertIn("ends Oct 26, 14:00 UTC", out["final"]["summary"])
        self.assertIn("works until Oct 26, 14:00 UTC", out["final"]["message"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class FunnelHealthAndSupport(unittest.TestCase):
    def test_the_funnel_is_bars_with_counts_and_conversion_from_the_named_step(self):
        out = run(actions=[go("funnel")], queries=[
            q("labels", "[data-hook='admin-funnel-step'] .adm-funnel__label", "texts"),
            q("counts", "[data-hook='admin-funnel-count']", "texts"),
            q("conv", "[data-hook='admin-funnel-conv']", "texts"),
            q("sources", "[data-hook='admin-source-row']", "attrs", attr="data-source"),
            q("note", "[data-hook='admin-funnel-note']"),
        ])
        f = out["final"]
        self.assertEqual(f["labels"][0], "Landing page views")
        self.assertEqual(f["counts"][:5], ["212", "61", "24", "33", "14"])
        self.assertEqual(f["conv"][0], "—")
        self.assertEqual(f["conv"][1], "28.8%")                                  # from the row above
        self.assertEqual(f["conv"][2], "11.3% of landing page views")             # from a named, earlier step
        self.assertEqual(f["sources"], ["reddit-mlb", "x-thread", "internal-test"])
        self.assertIn("measured from the step named", f["note"])
        self.assertNotIn("Small sample", f["note"])

    def test_a_small_funnel_says_it_is_small(self):
        small = copy.deepcopy(F.build(NOW)["/admin/funnel"])
        for step in small["steps"]:
            step["count"] = min(step["count"], 9)
        out = run(routes=routes(**{"/admin/funnel": [200, small]}), actions=[go("funnel")],
                  queries=[q("note", "[data-hook='admin-funnel-note']")])
        self.assertIn("Small sample", out["final"]["note"])

    def test_the_bar_widths_are_relative_to_the_biggest_step(self):
        out = run(actions=[go("funnel")], queries=[q("fills", "[data-hook='admin-funnel-fill']", "count")])
        self.assertEqual(out["final"]["fills"], 10)

    def test_health_cards_are_green_amber_or_red_by_age_and_reasons_are_verbatim(self):
        out = run(actions=[go("health")], queries=[
            q("tones", "[data-hook='admin-health-card']", "attrs", attr="data-tone"),
            q("stores", "[data-hook='admin-health-card']", "attrs", attr="data-store"),
            q("words", "[data-hook='admin-health-word']", "texts"),
            q("big", "[data-hook='admin-health-big']", "texts"),
            q("reasons", "[data-hook='admin-health-reasons'] li", "texts"),
            q("banner", "[data-hook='admin-health-summary'] .adm-banner__word"),
        ])
        f = out["final"]
        tone = dict(zip(f["stores"], f["tones"]))
        word = dict(zip(f["stores"], f["words"]))
        big = dict(zip(f["stores"], f["big"]))
        self.assertEqual(tone["app_db"], "ok")
        self.assertEqual(tone["odds_multibook"], "ok")
        self.assertEqual((tone["odds_snapshots"], word["odds_snapshots"]), ("ok", "Fresh"))
        self.assertEqual((tone["f5_close"], word["f5_close"]), ("warn", "Aging"))          # 40 hours
        self.assertEqual((tone["prop_listing"], word["prop_listing"]), ("bad", "Stale"))   # 5 days
        self.assertEqual((tone["probables_watch"], word["probables_watch"]), ("warn", "Empty"))
        self.assertEqual((tone["transactions_watch"], word["transactions_watch"]), ("warn", "Missing"))
        self.assertEqual((tone["lineups_watch"], word["lineups_watch"]), ("bad", "Unreadable"))
        self.assertEqual((tone["fresh_standings"], tone["fresh_results"]), ("bad", "ok"))
        self.assertEqual(big["odds_multibook"], "2h 14m")
        self.assertEqual(f["banner"], "Degraded")
        self.assertEqual(f["reasons"], F.build(NOW)["/admin/overview"]["store_health"]["reasons"])
        for name in ("app_db", "checkout", "version"):
            self.assertIn(name, f["stores"])

    def test_a_server_reason_is_shown_exactly_as_sent(self):
        out = run(actions=[go("health")], queries=[q("r", "[data-store='lineups_watch'] [data-hook='admin-health-reason']")])
        self.assertEqual(out["final"]["r"], "lineups_watch.jsonl holds 12 row(s) but none carry a parseable fetched_utc")

    def test_an_unreachable_database_is_red(self):
        broken = copy.deepcopy(F.build(NOW)["/admin/overview"])
        broken["store_health"]["app_db"] = {"reachable": False, "path": "/x", "reason": "disk I/O error"}
        out = run(routes=routes(**{"/admin/overview": [200, broken]}), actions=[go("health")], queries=[
            q("tone", "[data-store='app_db']", "attr", attr="data-tone"),
            q("reason", "[data-store='app_db'] [data-hook='admin-health-reason']")])
        self.assertEqual(out["final"]["tone"], "bad")
        self.assertEqual(out["final"]["reason"], "disk I/O error")

    def test_support_shows_open_messages_first_and_can_filter(self):
        out = run(actions=[go("support")], queries=[
            q("ids", "[data-hook='admin-support-message']", "attrs", attr="data-message-id"),
            q("filters", "[data-hook='admin-support-filter-opt']", "texts"),
            q("body", "[data-message-id='3'] .adm-msg__body"),
        ])
        f = out["final"]
        self.assertEqual(f["ids"], ["3"])
        self.assertEqual(f["filters"], ["Open 1", "Answered 1", "Closed 1", "All 3"])
        self.assertIn("Can you send a new one?", f["body"])
        everything = run(actions=[go("support"),
                                  dict(do="click", sel="[data-hook='admin-support-filter-opt'][data-filter='all']")],
                         queries=[q("ids", "[data-hook='admin-support-message']", "attrs", attr="data-message-id")])
        self.assertEqual(everything["final"]["ids"], ["3", "2", "1"])

    def test_marking_a_message_posts_to_the_documented_route_and_re_reads_the_inbox(self):
        out = run(routes=routes(**{"POST /admin/support/3/status": [200, {"id": 3, "status": "answered"}]}),
                  actions=[go("support"), dict(do="click", sel="[data-message-id='3'] [data-hook='admin-support-set']")],
                  queries=[q("targets", "[data-message-id='3'] [data-hook='admin-support-set']", "texts")])
        self.assertEqual([(p["url"], p["body"]) for p in out["posts"]],
                         [("/admin/support/3/status", {"status": "answered"})])
        self.assertEqual(out["gets"].count("/admin/support"), 2)

    def test_a_support_message_is_text_never_markup(self):
        evil = copy.deepcopy(F.build(NOW)["/admin/support"])
        evil["messages"][0]["subject"] = "<img src=x onerror=alert(1)>"
        out = run(routes=routes(**{"/admin/support": [200, evil]}), actions=[go("support")],
                  queries=[q("subject", "[data-message-id='3'] .adm-msg__subject"),
                           q("imgs", "img", "count")])
        self.assertEqual(out["final"]["subject"], "<img src=x onerror=alert(1)>")
        self.assertEqual(out["final"]["imgs"], 0)


class ThePageSource(unittest.TestCase):
    def setUp(self):
        self.html = (WEB / "admin.html").read_text(encoding="utf-8")

    def test_the_five_tabs_and_the_private_page_basics(self):
        for route in ("overview", "people", "funnel", "health", "support"):
            self.assertIn(f'data-route="{route}"', self.html)
            self.assertIn(f'data-hook="admin-view-{route}"', self.html)
        self.assertIn('name="robots" content="noindex, nofollow"', self.html)
        self.assertIn("Sign out of admin", self.html)
        self.assertIn('<script type="module" src="js/admin-app.js"></script>', self.html)
        self.assertEqual(len(re.findall(r"<script\b", self.html)), 1)

    def test_the_token_field_is_a_password_field_that_is_never_prefilled(self):
        field = re.search(r"<input[^>]*data-hook=\"admin-token-input\"[^>]*>", self.html).group(0)
        self.assertIn('type="password"', field)
        self.assertNotIn("value=", field)

    def test_the_site_style_is_reused_not_reinvented(self):
        for sheet in ("fonts.css", "tokens.css", "base.css", "components.css", "admin.css"):
            self.assertIn(f"css/{sheet}", self.html)
        css = (WEB / "css" / "admin.css").read_text(encoding="utf-8")
        self.assertIn("font-variant-numeric: tabular-nums", css)
        # colours come from the site's tokens; only white and one hover tint are literal
        self.assertLessEqual(set(re.findall(r"#[0-9A-Fa-f]{3,8}\b", css)), {"#FFFFFF", "#FF566C"})


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def js(self, body):
        return run_js('import * as V from "./admin-views.js";\nimport * as U from "./admin-ui.js";\n' + body)

    def test_store_tone_thresholds(self):
        tones = self.js("""
          const t = (status, age) => V.storeTone({status, newest_row_age_seconds: age});
          console.log(JSON.stringify([t("ok", 60), t("ok", 24*3600), t("ok", 24*3600+1), t("ok", 72*3600),
            t("ok", 72*3600+1), t("ok", null), t("missing", null), t("empty", null), t("archived_only", null),
            t("unreadable", null)]));""")
        self.assertEqual(tones, ["ok", "ok", "warn", "warn", "bad", "warn", "warn", "warn", "warn", "bad"])

    def test_spans_and_dates(self):
        out = self.js("""
          console.log(JSON.stringify([U.spanLabel(25*60000), U.spanLabel(310*60000), U.spanLabel(30*3600000),
            U.spanLabel(5*86400000+3*3600000), U.fmtInt(1234567), U.fmtInt(null), U.dayLabel("2026-10-19"),
            U.momentLabel("2026-10-19T14:03:00+00:00"), U.parseTime("2026-10-19 14:03:00") === Date.parse("2026-10-19T14:03:00Z")]));""")
        self.assertEqual(out, ["25m", "5h 10m", "1d 6h", "5d 3h", "1,234,567", "—", "Oct 19",
                               "Oct 19, 14:03 UTC", True])

    def test_filter_people_matches_email_or_exact_id(self):
        out = self.js("""
          const rows = [{id: 1, email: "A@x.test", state: {group: "waitlist"}}, {id: 12, email: "b@x.test", state: {group: "free"}}];
          console.log(JSON.stringify([V.filterPeople(rows, "a@", "all").length, V.filterPeople(rows, "12", "all").length,
            V.filterPeople(rows, "1", "all").length, V.filterPeople(rows, "", "free").length]));""")
        self.assertEqual(out, [1, 1, 1, 1])


if __name__ == "__main__":
    unittest.main()
