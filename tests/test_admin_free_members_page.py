"""The admin page's Free members section, run for real under node.

Owner decision (2026-10-19): the owner can make a person a free member (full
access, no card, no end date) from web/admin.html. This file runs the real
web/js/admin.js (and web/js/billing.js) against a small fake DOM and a stubbed
fetch -- the pattern of tests/test_admin_testers_page.py -- and pins what the
page must do:

  * a "Free members" section with an email box, a reason box and a button that
    says "Give free access forever";
  * after a grant, the token ONCE in a read-only box with a copy button, the
    sign-in page's address (which holds no token), a "copy the message" button,
    and the line that it is not kept and cannot be shown again;
  * a list of free members with who, when, why, signed in, and state, with
    Revoke and New token actions that refuse to send without a typed reason;
  * a server refusal is shown in the server's own words and shows no token;
  * a waitlisted user in the Users list gets "Approve as free member", which asks
    for the reason first and sends nothing when the answer is empty;
  * the token never reaches storage, a URL or the console, and is gone when the
    section is rebuilt;
  * a free member's Billing page says "Free member" and offers no Subscribe.

Skipped when node is not installed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.listeners = {}; this.value = "";
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.push(c); return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null; return c;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  focus() { globalThis.__focused = this; }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  byHook(name) { return this._all([]).filter((n) => n.attrs["data-hook"] === name); }
  one(name) { return this.byHook(name)[0] || null; }
}

const writes = { local: [], session: [] };
globalThis.document = {
  createElement: (t) => new Elem(t),
  createTextNode: (t) => new TextNode(t),
  addEventListener() {}, querySelector: () => null,
};
const prompts = [];
globalThis.window = {
  sessionStorage: {
    getItem: () => "the-admin-token",
    setItem: (k, v) => writes.session.push([k, v]), removeItem() {},
  },
  localStorage: {
    getItem: () => null, setItem: (k, v) => writes.local.push([k, v]), removeItem() {},
  },
  location: { search: "", hash: "", pathname: "/web/admin.html", href: "http://x/web/admin.html?a=1#b" },
  prompt: (message) => { prompts.push(String(message)); return "prompt" in scenario ? scenario.prompt : null; },
};
globalThis.sessionStorage = globalThis.window.sessionStorage;
globalThis.localStorage = globalThis.window.localStorage;

const logged = [];
for (const level of ["log", "info", "warn", "error", "debug"]) {
  console[level] = (...args) => logged.push(args.map(String).join(" "));
}
const copied = [];
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: { clipboard: { writeText: async (t) => { copied.push(t); } } },
});

const scenario = JSON.parse(process.env.SCENARIO);
const calls = [];
const queue = {};
for (const [key, list] of Object.entries(scenario.responses || {})) queue[key] = list.slice();
globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || "GET";
  const key = method + " " + url;
  calls.push({ url: String(url), method, headers: (init && init.headers) || {},
               body: init && init.body ? JSON.parse(init.body) : null });
  const list = queue[key];
  if (!list || !list.length) throw new Error("unexpected request " + key);
  const step = list.length > 1 ? list.shift() : list[0];
  return { ok: step.status < 400, status: step.status, text: async () => JSON.stringify(step.body) };
};

const admin = await import("./admin.js");
const host = new Elem("div");
const usersHost = new Elem("div");
const changes = [];
const onChange = async () => { changes.push(calls.length); };
const press = async (node, event = {}) => {
  const fn = (node.listeners[event.type] || node.listeners.click || [])[0];
  await fn(Object.assign({ preventDefault() {} }, event));
};
const flat = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(flat).join(" "));
const snapshot = () => ({
  count: (host.one("admin-comps-count") || { textContent: null }).textContent,
  button: (host.one("admin-comp-grant") || { textContent: null }).textContent,
  formStatus: (host.one("admin-comp-form-status") || { textContent: null }).textContent,
  empty: host.byHook("admin-comps-empty").length,
  headers: host.one("admin-comps-table")
    ? host.one("admin-comps-table")._all([]).filter((n) => n.tagName === "TH")
        .map((n) => n.textContent) : [],
  rows: host.byHook("admin-comp-row").map((r) => ({
    userId: r.attrs["data-user-id"], cells: r.children.map((c) => flat(c).trim().replace(/\s+/g, " ")),
    reason: r.one("admin-comp-reason").textContent,
    state: r.one("admin-comp-state").textContent,
    signedIn: r.one("admin-comp-signed-in").textContent,
    hasRevoke: r.byHook("admin-comp-revoke").length,
    hasReissue: r.byHook("admin-comp-reissue").length,
    status: r.one("admin-comp-row-status") ? r.one("admin-comp-row-status").textContent : null,
  })),
  result: host.one("admin-comp-result") ? {
    summary: host.one("admin-comp-result-summary").textContent,
    tokenValue: host.one("admin-comp-token").attrs.value,
    tokenReadonly: "readonly" in host.one("admin-comp-token").attrs,
    copyLabel: host.one("admin-comp-copy").textContent,
    link: host.one("admin-comp-signin-link").attrs.href,
    linkText: host.one("admin-comp-signin-link").textContent,
    messageLabel: host.one("admin-comp-copy-message").textContent,
    note: host.one("admin-comp-token-note").textContent,
  } : null,
  authError: host.byHook("admin-auth-error").length + host.byHook("admin-auth-invalid").length,
});
const usersSnapshot = () => usersHost.byHook("admin-user-row").map((r) => ({
  userId: r.attrs["data-user-id"],
  comp: r.one("admin-user-comp").textContent,
  approve: r.byHook("admin-user-approve-free").length,
  approveLabel: r.one("admin-user-approve-free") ? r.one("admin-user-approve-free").textContent : null,
  approveStatus: r.one("admin-user-approve-status") ? r.one("admin-user-approve-status").textContent : null,
  testerShortcut: r.byHook("admin-user-grant-tester").length,
}));

const out = {};
if (scenario.kind === "billing") {
  const billing = await import("./billing.js");
  await billing.renderBilling(host);
  const all = host._all([]);
  out.billing = {
    state: host.one("billing-free-state") ? host.one("billing-free-state").textContent : null,
    panels: host.byHook("billing-free-member").length,
    subscribe: host.byHook("billing-subscribe").length,
    cancel: host.byHook("billing-cancel").length,
    reactivate: host.byHook("billing-reactivate").length,
    text: flat(host).replace(/\s+/g, " "),
  };
} else {
  await admin.mountComps(host, onChange);
  if (scenario.kind === "render") {
    out.snap = snapshot();
  } else if (scenario.kind === "grant") {
    if (scenario.email !== undefined) host.one("admin-comp-email").value = scenario.email;
    if (scenario.reason !== undefined) host.one("admin-comp-reason-input").value = scenario.reason;
    await press(host.one("admin-comp-form"), { type: "submit" });
    out.snap = snapshot();
    out.fields = [host.one("admin-comp-email").value, host.one("admin-comp-reason-input").value];
    if (scenario.copy) { await press(host.one("admin-comp-copy")); out.afterCopy = snapshot().result; }
    if (scenario.copyMessage) { await press(host.one("admin-comp-copy-message")); out.afterMessage = snapshot().result; }
    if (scenario.rebuild) { await admin.mountComps(host, onChange); out.rebuilt = snapshot(); }
  } else if (scenario.kind === "row") {
    const row = host.byHook("admin-comp-row")[scenario.row || 0];
    if (scenario.reason !== undefined) row.one("admin-comp-row-reason").value = scenario.reason;
    await press(row.one(scenario.action));
    out.snap = snapshot();
  } else if (scenario.kind === "approve") {
    admin.renderUsers(usersHost, scenario.users);
    out.users = usersSnapshot();
    const buttons = usersHost.byHook("admin-user-approve-free");
    if (buttons.length) await press(buttons[scenario.button || 0]);
    out.afterUsers = usersSnapshot();
    out.snap = snapshot();
  }
}
out.calls = calls;
out.writes = writes;
out.logged = logged;
out.copied = copied;
out.prompts = prompts;
out.changes = changes;
process.stdout.write("@@" + JSON.stringify(out) + "\n");
"""

SECRET = "tok_SECRET_value_that_must_never_leak_0123456789"
COMPS = {
    "comps": [
        {"user_id": 21, "email": "jacob@example.com", "status": "active",
         "granted_at": "2026-10-19T12:00:00+00:00", "reason": "early-access signup",
         "granted_by": "admin", "revoked_at": None, "revoked_reason": None,
         "first_used_at": "2026-10-19T13:00:00+00:00", "active": True},
        {"user_id": 22, "email": "gone@example.com", "status": "active",
         "granted_at": "2026-10-10T08:00:00+00:00", "reason": "friend",
         "granted_by": "admin", "revoked_at": "2026-10-15T09:30:00+00:00",
         "revoked_reason": "asked to leave", "first_used_at": None, "active": False},
    ],
    "active": 1, "token_years": 10,
}
EMPTY = {"comps": [], "active": 0, "token_years": 10}
GRANTED = {"user_id": 23, "email": "dee@example.com", "token": SECRET,
           "expires_at": "2036-10-16T16:45:00+00:00", "kind": "new_email", "revoked_tokens": 0}
AFTER_GRANT = {"comps": COMPS["comps"][:1], "active": 2, "token_years": 10}
USERS = [
    {"id": 1, "email": "wait@example.com", "status": "waitlisted", "plan": "none",
     "created_at": "2026-10-18", "tester": False, "comp": False, "comp_revoked": False},
    {"id": 2, "email": "free@example.com", "status": "active", "plan": "none",
     "created_at": "2026-10-17", "tester": False, "comp": True, "comp_revoked": False},
    {"id": 3, "email": "ended@example.com", "status": "waitlisted", "plan": "none",
     "created_at": "2026-10-16", "tester": False, "comp": False, "comp_revoked": True},
    {"id": 4, "email": "plain@example.com", "status": "invited", "plan": "none",
     "created_at": "2026-10-15", "tester": False, "comp": False, "comp_revoked": False},
]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class AdminFreeMembersSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="admin_comps_")
        shutil.copytree(JS, Path(cls.tmp) / "js")
        (Path(cls.tmp) / "js" / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (Path(cls.tmp) / "js" / "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_page(self, **scenario):
        scenario.setdefault("responses", {})
        scenario["responses"].setdefault("GET /admin/comps", [{"status": 200, "body": COMPS}])
        done = subprocess.run(["node", "harness.mjs"], cwd=Path(self.tmp) / "js",
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        line = [ln for ln in done.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def grant_responses(self):
        return {"POST /admin/comps": [{"status": 200, "body": GRANTED}],
                "GET /admin/comps": [{"status": 200, "body": COMPS},
                                     {"status": 200, "body": AFTER_GRANT}]}

    # ---- the form and the list -------------------------------------------------

    def test_the_section_has_the_form_and_the_one_button_the_owner_presses(self):
        snap = self.run_page(kind="render")["snap"]
        self.assertEqual(snap["button"], "Give free access forever")
        self.assertEqual(snap["count"], "1 free member")

    def test_the_count_is_plural_when_it_should_be_and_the_empty_list_says_so(self):
        snap = self.run_page(kind="render", responses={"GET /admin/comps": [
            {"status": 200, "body": EMPTY}]})["snap"]
        self.assertEqual((snap["count"], snap["empty"]), ("0 free members", 1))
        snap = self.run_page(kind="render", responses={"GET /admin/comps": [
            {"status": 200, "body": dict(COMPS, active=2)}]})["snap"]
        self.assertEqual(snap["count"], "2 free members")

    def test_the_list_shows_who_when_why_signed_in_and_state(self):
        snap = self.run_page(kind="render")["snap"]
        self.assertEqual(snap["headers"], ["email", "status", "given", "why", "signed in",
                                           "state", "actions"])
        jacob, gone = snap["rows"]
        self.assertEqual(jacob["cells"][:6], [
            "jacob@example.com", "active", "2026-10-19 12:00 UTC", "early-access signup",
            "yes", "free member"])
        self.assertEqual((jacob["hasRevoke"], jacob["hasReissue"]), (1, 1))
        self.assertEqual(gone["state"], "revoked 2026-10-15 09:30 UTC: asked to leave")
        self.assertEqual((gone["signedIn"], gone["hasRevoke"], gone["hasReissue"]), ("no", 0, 0))

    def test_a_suspended_member_is_shown_as_on_hold_not_as_active(self):
        body = json.loads(json.dumps(COMPS))
        body["comps"][0].update(status="suspended", active=False)
        snap = self.run_page(kind="render", responses={"GET /admin/comps": [
            {"status": 200, "body": body}]})["snap"]
        self.assertEqual(snap["rows"][0]["state"], "on hold (account suspended)")

    # ---- granting --------------------------------------------------------------

    def test_a_grant_posts_the_email_and_the_reason_and_shows_the_token_once(self):
        out = self.run_page(kind="grant", email="dee@example.com", reason="friend of the project",
                            responses=self.grant_responses())
        posts = [c for c in out["calls"] if c["method"] == "POST"]
        self.assertEqual([(c["url"], c["body"]) for c in posts], [
            ("/admin/comps", {"email": "dee@example.com", "reason": "friend of the project"})])
        self.assertEqual(posts[0]["headers"]["X-Admin-Token"], "the-admin-token")
        result = out["snap"]["result"]
        self.assertEqual(result["summary"],
                         "Free access given for dee@example.com. It does not expire; it works "
                         "until you revoke it.")
        self.assertEqual((result["tokenValue"], result["tokenReadonly"]), (SECRET, True))
        self.assertEqual(result["copyLabel"], "Copy")
        self.assertIn("not stored and cannot be shown again", result["note"])
        self.assertEqual(out["fields"], ["", ""])
        self.assertEqual(out["snap"]["count"], "2 free members")

    def test_the_signin_address_is_beside_the_admin_page_and_holds_no_token(self):
        result = self.run_page(kind="grant", email="dee@example.com", reason="why",
                               responses=self.grant_responses())["snap"]["result"]
        self.assertEqual(result["link"], "http://x/web/index.html#/signin")
        self.assertEqual(result["linkText"], result["link"])
        self.assertNotIn(SECRET, result["link"])

    def test_copy_puts_the_token_on_the_clipboard_and_the_message_names_the_page(self):
        out = self.run_page(kind="grant", email="dee@example.com", reason="why", copy=True,
                            copyMessage=True, responses=self.grant_responses())
        self.assertEqual(out["afterCopy"]["copyLabel"], "Copied")
        self.assertEqual(out["copied"][0], SECRET)
        self.assertEqual(out["afterMessage"]["messageLabel"], "Message copied")
        message = out["copied"][1]
        self.assertIn(SECRET, message)
        self.assertIn("http://x/web/index.html#/signin", message)
        self.assertIn("free LINEHOUND access", message)
        self.assertNotRegex(message, r"(?i)profit|guarantee|winning|edge")

    def test_the_token_never_reaches_storage_a_url_or_the_console(self):
        out = self.run_page(kind="grant", email="dee@example.com", reason="why", copy=True,
                            responses=self.grant_responses())
        self.assertEqual(out["writes"], {"local": [], "session": []})
        self.assertEqual(out["logged"], [])
        for call in out["calls"]:
            self.assertNotIn(SECRET, call["url"])
            self.assertNotIn(SECRET, json.dumps(call["headers"]))
            if call["method"] == "GET":
                self.assertIsNone(call["body"])
        # and the listing after the grant shows no token anywhere
        self.assertNotIn(SECRET, json.dumps({k: v for k, v in out["snap"].items() if k != "result"}))

    def test_rebuilding_the_section_removes_the_token_from_the_screen(self):
        responses = self.grant_responses()
        responses["GET /admin/comps"].append({"status": 200, "body": AFTER_GRANT})
        out = self.run_page(kind="grant", email="dee@example.com", reason="why", rebuild=True,
                            responses=responses)
        self.assertIsNotNone(out["snap"]["result"])
        self.assertIsNone(out["rebuilt"]["result"])

    def test_both_boxes_are_required_and_nothing_is_sent_without_them(self):
        out = self.run_page(kind="grant", email="", reason="why")
        self.assertEqual(out["snap"]["formStatus"], "Enter an email.")
        out2 = self.run_page(kind="grant", email="dee@example.com", reason="  ")
        self.assertEqual(out2["snap"]["formStatus"], "Type why: it is kept in the log.")
        for o in (out, out2):
            self.assertEqual([c for c in o["calls"] if c["method"] == "POST"], [])
            self.assertIsNone(o["snap"]["result"])

    def test_a_refusal_is_shown_in_the_servers_words_with_no_token(self):
        refusal = {"status": 409, "body": {"detail": {
            "error": "has_subscription",
            "message": "this person has a live paid subscription; free access was not granted"}}}
        out = self.run_page(kind="grant", email="paid@example.com", reason="why",
                            responses={"POST /admin/comps": [refusal]})
        self.assertEqual(out["snap"]["formStatus"],
                         "this person has a live paid subscription; free access was not granted")
        self.assertIsNone(out["snap"]["result"])
        self.assertEqual(out["fields"], ["paid@example.com", "why"])    # kept so it can be fixed

    def test_a_wrong_admin_token_says_so(self):
        out = self.run_page(kind="grant", email="a@example.com", reason="why", responses={
            "POST /admin/comps": [{"status": 401, "body": {"detail": "bad"}}]})
        self.assertIn("admin token was rejected", out["snap"]["formStatus"])

    # ---- revoke and new token --------------------------------------------------

    def test_revoke_needs_a_reason_then_posts_it_and_reloads_everything(self):
        out = self.run_page(kind="row", action="admin-comp-revoke", reason="  ")
        self.assertEqual(out["snap"]["rows"][0]["status"], "Type the reason first: why is the access ending?")
        self.assertEqual([c for c in out["calls"] if c["method"] == "POST"], [])
        out = self.run_page(kind="row", action="admin-comp-revoke", reason="asked to leave",
                            responses={"POST /admin/comps/revoke": [
                                {"status": 200, "body": {"user_id": 21, "revoked_tokens": 1}}],
                                "GET /admin/comps": [{"status": 200, "body": COMPS},
                                                     {"status": 200, "body": EMPTY}]})
        posts = [c for c in out["calls"] if c["method"] == "POST"]
        self.assertEqual([(c["url"], c["body"]) for c in posts],
                         [("/admin/comps/revoke", {"user_id": 21, "reason": "asked to leave"})])
        self.assertEqual(out["snap"]["count"], "0 free members")
        self.assertEqual(len(out["changes"]), 1)             # the Users list was told

    def test_new_token_posts_the_support_reissue_and_shows_the_token_once(self):
        out = self.run_page(kind="row", action="admin-comp-reissue", reason="lost it, ticket 7",
                            responses={"POST /admin/users/reissue": [
                                {"status": 200, "body": dict(GRANTED, user_id=21,
                                                             email="jacob@example.com",
                                                             kind="comp", revoked_tokens=1)}]})
        posts = [c for c in out["calls"] if c["method"] == "POST"]
        self.assertEqual([(c["url"], c["body"]) for c in posts], [
            ("/admin/users/reissue", {"user_id": 21, "reason": "lost it, ticket 7"})])
        result = out["snap"]["result"]
        self.assertEqual(result["summary"], "New token issued for jacob@example.com. It does not "
                                            "expire; it works until you revoke it.")
        self.assertEqual(result["tokenValue"], SECRET)
        out = self.run_page(kind="row", action="admin-comp-reissue", reason="")
        self.assertEqual(out["snap"]["rows"][0]["status"], "Type the reason first: what did you verify?")
        self.assertEqual([c for c in out["calls"] if c["method"] == "POST"], [])

    # ---- the Users list ---------------------------------------------------------

    def test_only_a_waitlisted_user_who_is_not_a_free_member_gets_the_approve_button(self):
        out = self.run_page(kind="approve", users=USERS, prompt=None)
        by_id = {u["userId"]: u for u in out["users"]}
        self.assertEqual({k: v["approve"] for k, v in by_id.items()},
                         {"1": 1, "2": 0, "3": 1, "4": 0})
        self.assertEqual(by_id["1"]["approveLabel"], "Approve as free member")
        self.assertEqual({k: v["comp"] for k, v in by_id.items()},
                         {"1": "no", "2": "yes", "3": "ended", "4": "no"})

    def test_approving_asks_for_the_reason_then_grants_by_user_id(self):
        out = self.run_page(kind="approve", users=USERS, prompt="signed up for early access",
                            responses=self.grant_responses())
        self.assertEqual(len(out["prompts"]), 1)
        self.assertIn("wait@example.com", out["prompts"][0])
        posts = [c for c in out["calls"] if c["method"] == "POST"]
        self.assertEqual([(c["url"], c["body"]) for c in posts],
                         [("/admin/comps", {"user_id": 1, "reason": "signed up for early access"})])
        self.assertEqual(out["snap"]["result"]["tokenValue"], SECRET)
        self.assertEqual(len(out["changes"]), 1)             # so the Users list refreshes

    def test_cancelling_or_leaving_the_reason_empty_sends_nothing(self):
        for answer in (None, "", "   "):
            with self.subTest(answer=answer):
                out = self.run_page(kind="approve", users=USERS, prompt=answer)
                self.assertEqual([c for c in out["calls"] if c["method"] == "POST"], [])
                self.assertEqual(out["afterUsers"][0]["approveStatus"],
                                 "Not approved: a reason is required.")
                self.assertIsNone(out["snap"]["result"])

    def test_an_approve_the_server_refuses_shows_its_words_beside_the_user(self):
        refusal = {"status": 409, "body": {"detail": {
            "error": "user_suspended", "message": "this account is suspended"}}}
        out = self.run_page(kind="approve", users=USERS, prompt="why",
                            responses={"POST /admin/comps": [refusal]})
        self.assertEqual(out["afterUsers"][0]["approveStatus"], "this account is suspended")
        self.assertIsNone(out["snap"]["result"])

    # ---- the member's own billing page -------------------------------------------

    def test_a_free_members_billing_page_says_free_member_and_offers_nothing_to_buy(self):
        out = self.run_page(kind="billing", responses={"GET /billing/status": [{
            "status": 200, "body": {"status": "comp", "plan": "comp", "renews": False,
                                    "label": "Free member", "granted_at": "2026-10-19"}}]})
        billing = out["billing"]
        self.assertEqual((billing["state"], billing["panels"]), ("Free member", 1))
        self.assertEqual((billing["subscribe"], billing["cancel"], billing["reactivate"]), (0, 0, 0))
        self.assertIn("nothing to pay and nothing renews", billing["text"])


class TheSectionIsOnThePage(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "web" / "admin.html").read_text(encoding="utf-8")
        self.js = (JS / "admin.js").read_text(encoding="utf-8")

    def test_the_dashboard_offers_free_member_actions_from_its_people_tab(self):
        # Redrawn 2026-10-19: the classic Free members section this file runs above is no longer
        # on the page; the owner gives, re-issues and revokes from the People tab and Add person.
        html = (ROOT / "web" / "admin.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<section[^>]*data-hook="admin-view-people"[^>]*\shidden')
        app = (JS / "admin-app.js").read_text(encoding="utf-8")
        for needle in ('adminPost("/admin/comps", { user_id: row.id, reason: v.reason })',
                       'adminPost("/admin/comps/revoke", { user_id: row.id, reason: v.reason })',
                       'adminPost("/admin/users/reissue", { user_id: row.id, reason: v.reason })',
                       'adminPost("/admin/comps", { email: v.email, reason: v.reason })'):
            self.assertIn(needle, app)

    def test_the_classic_section_is_still_wired_for_the_tests_above(self):
        self.assertIn("export async function mountComps", self.js)
        self.assertIn("approveFreeMember", self.js)

    def test_the_owners_button_label_is_the_pages_label(self):
        self.assertIn('text: "Give free access forever"', self.js)
        guide = (ROOT / "docs" / "support" / "FREE_MEMBERS.md")
        if guide.is_file():
            text = " ".join(guide.read_text(encoding="utf-8").split())
            for label in ("Give free access forever", "Approve as free member", "Revoke", "New token"):
                self.assertIn(label, text)

    def test_the_page_never_builds_the_token_into_an_address(self):
        self.assertNotRegex(self.js, r"[?&]token=")
        self.assertNotRegex(self.js, r"\$\{[^}]*[Tt]oken[^}]*\}")
        self.assertNotIn("window.localStorage", self.js)


if __name__ == "__main__":
    unittest.main()
